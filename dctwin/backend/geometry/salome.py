from pathlib import Path

import click
from docker.errors import ContainerError

from dctwin.backend.core import Backend
from dctwin.backend import template_env
from dctwin.config import environ
from dctwin.models.constructions import Room


class SalomeBackend(Backend):
    docker_image = 'charact3/salome-9'

    def run(self, room: Room):
        self._pre_process(room)
        if not self.dry_run:
            self._run_backend()
        self._post_process()

    def _pre_process(self, room: Room):
        """Prepare files needed"""
        image = self.client.images.get(self.docker_image)
        if image is None:
            click.echo('Salome image not existed, try to pull...')
            self.client.images.pull(self.docker_image)

        environ.GEOMETRY_DIR.mkdir(parents=True, exist_ok=True)

        geometry_script = Path(environ.GEOMETRY_DIR, 'geometry_script.py')
        geometry_description = Path(environ.GEOMETRY_DIR, 'geometry.json')
        with open(geometry_description, 'w') as f:
            f.write(room.json())
        template = template_env.get_template('salome/geometry_script.py')
        with open(geometry_script, 'w') as f:
            f.write(template.render())
        self._clean_files = [geometry_script, geometry_description]

    def _post_process(self):
        for file in self._clean_files:
            file.unlink()

    def _run_backend(self):
        working_path = '/output'
        geometry_file = f'{working_path}/geometry.json'
        try:
            container = self.client.containers.run(
                self.docker_image,
                command=['salome', 'start', '-t', 'geometry_script.py'],
                auto_remove=True,
                volumes={
                    str(environ.GEOMETRY_DIR): {
                        'bind': working_path,
                        'mode': 'rw',
                    },
                },
                environment={
                    'SRC_PATH': geometry_file,
                    'OUTPUT_PATH': working_path,
                },
                working_dir=working_path,
                detach=True)
            stream = container.logs(stream=True, follow=True)
            for log in stream:
                click.echo(log, nl=False)
        except ContainerError as e:
            click.echo('Run salome failed:')
            click.echo(str(e.stderr))
            raise e
