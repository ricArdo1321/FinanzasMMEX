using FinanzasMMEX.Core.Cli;

namespace FinanzasMMEX.App.ViewModels;

public sealed class MainViewModel
{
    public MainViewModel(ICliRunner runner)
    {
        Pendings = new PendingsViewModel(runner);
        QuickAdd = new QuickAddViewModel(runner);
    }

    public PendingsViewModel Pendings { get; }

    public QuickAddViewModel QuickAdd { get; }
}
