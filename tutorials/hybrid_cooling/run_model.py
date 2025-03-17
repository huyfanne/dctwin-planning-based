from pathlib import Path
from dctwin.managers import HVACManager
from dctwin.utils import read_engine_config


def get_action_list(step) -> list:
    acts = [ 22, 1, 25, 0.006*2*2, 14, 27, ]
    return acts


def get_external_inputs(step) -> dict:
    return {
        "outdoor_temperature": 27.,
        "Data Hall 1A server-1": 100.,
        "Data Hall 1A server-2": 100.,
    }


def run(
    engine_config: str | Path,
):
    config = read_engine_config(engine_config)
    manager = HVACManager(
        config=config,
    )
    for episode in range(1):
        manager.reset()
        step = 0
        while True:
            acts = manager.format_actions(get_action_list(step))
            inps = manager.format_external_inputs(get_external_inputs(step))
            manager.run(acts=acts, inps=inps)
            step += 1
            if manager.done:
                break


if __name__ == '__main__':
    run(
        engine_config=Path("configs/dt/env.prototxt"),
    )
