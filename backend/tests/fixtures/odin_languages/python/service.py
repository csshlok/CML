from .helpers import run

class Service(Base):
    def execute(self):
        return run()
