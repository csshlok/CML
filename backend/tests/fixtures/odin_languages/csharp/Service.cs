using Vault.Helpers;

class Service : Base, IRunnable {
    void Execute() { Runner.Run(); }
}
