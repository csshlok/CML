from .helpers import run

class Service(Base):  # noqa: F821 - intentionally unresolved cross-file parser fixture
    def execute(self):
        return run()
