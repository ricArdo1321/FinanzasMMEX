// GOOD: ViewModel with INotifyPropertyChanged, ObservableCollection<T>,
// async commands, no .Result / .Wait().
using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Runtime.CompilerServices;
using System.Threading.Tasks;

namespace FinanzasMMEX.App.ViewModels;

public sealed class ReviewQueueViewModel : INotifyPropertyChanged
{
    private bool _busy;
    public bool Busy
    {
        get => _busy;
        set { _busy = value; OnPropertyChanged(); }
    }

    public ObservableCollection<PendingTxViewModel> Pending { get; } = new();

    public async Task LoadAsync()
    {
        Busy = true;
        try
        {
            // Token expiration shown as metadata only — never the raw token.
            // var status = await _cli.InvokeAsync(...);
            // foreach (var item in items) Pending.Add(new PendingTxViewModel(item));
            await Task.CompletedTask;
        }
        finally { Busy = false; }
    }

    public event PropertyChangedEventHandler? PropertyChanged;
    private void OnPropertyChanged([CallerMemberName] string? name = null) =>
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
}

public sealed record PendingTxViewModel(string TxUid, string Merchant, decimal Amount);
