from pathlib import Path

from jinja2 import Environment, FileSystemLoader

template_dir = Path(Path(__file__).parent.parent, "templates")
template_env = Environment(
    loader=FileSystemLoader(template_dir),
    autoescape=True,
    trim_blocks=True,
    lstrip_blocks=True,
)
