import click

from dctwin.backend.foam import snappyhex, solver
from dctwin.backend.geometry import salome
from dctwin.models.constructions import Room


@click.group()
@click.option("--debug/--no-debug", default=False)
def cli(debug):
    click.echo("Debug mode is %s" % ("on" if debug else "off"))


@cli.command()
def geometry():
    room = Room.load("room.json")
    salome.run(room)


@cli.command()
def mesh():
    room = Room.load("room.json")
    snappyhex.run(room)


@cli.command()
@click.option("-o", "--output")
@click.option("--config", default=None)
@click.option("--steady", default=True)
@click.option("--write_interval", default=100)
@click.option("--delta_t", default=1)
@click.option("--end_time", default=500)
def solve(
    output, config: str, steady: bool, write_interval: int, delta_t: int, end_time: int
):
    click.echo(
        f"Running with: write_interval({write_interval}) "
        f"delta_t({delta_t}) end_time({end_time})"
    )
    room = Room.load("room.json")

    if config is not None:
        room.load_config(config)
    solver.run(
        room,
        steady=steady,
        output=output,
        write_interval=write_interval,
        delta_t=delta_t,
        end_time=end_time,
    )


if __name__ == "__main__":
    cli()
