from geniehive_control.main import create_app as create_control_app
from geniehive_node.main import create_app as create_node_app


def test_control_app_title() -> None:
    assert create_control_app().title == "GenieHive Control"


def test_node_app_title() -> None:
    assert create_node_app().title == "GenieHive Node"
