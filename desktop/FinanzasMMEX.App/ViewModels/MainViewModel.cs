using FinanzasMMEX.App.Mvvm;
using FinanzasMMEX.Core.Cli;

namespace FinanzasMMEX.App.ViewModels;

public sealed class MainViewModel : ViewModelBase
{
    public MainViewModel(ICliRunner runner)
    {
        Pendings = new PendingsViewModel(runner);
        QuickAdd = new QuickAddViewModel(runner);
    }

    public PendingsViewModel Pendings { get; }

    public QuickAddViewModel QuickAdd { get; }
}
