import vault.helpers.Runner;

class Service extends Base implements Runnable {
    void execute() { Runner.run(); }
}
