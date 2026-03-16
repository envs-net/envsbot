from utils.command import check_permission, Role


class DummyCmd:
    role = Role.ADMIN


def test_admin_allowed():
    assert check_permission(Role.ADMIN, DummyCmd())


def test_user_denied():
    assert not check_permission(Role.USER, DummyCmd())
