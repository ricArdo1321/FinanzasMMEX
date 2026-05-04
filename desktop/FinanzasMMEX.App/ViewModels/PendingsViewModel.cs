using System.Collections.ObjectModel;
using FinanzasMMEX.App.Mvvm;
using FinanzasMMEX.Core.Cli;
using FinanzasMMEX.Core.Models;
using FinanzasMMEX.Core.Services;

namespace FinanzasMMEX.App.ViewModels;

public sealed class PendingsViewModel : ViewModelBase
{
    private readonly ICliRunner _runner;

    private string _ownerFilter = string.Empty;
    private string _accountFilter = string.Empty;
    private string _statusFilter = "pending";
    private bool _needsReviewOnly;
    private string _statusMessage = string.Empty;
    private bool _isBusy;

    public PendingsViewModel(ICliRunner runner)
    {
        _runner = runner ?? throw new ArgumentNullException(nameof(runner));
        Items = new ObservableCollection<PendingTx>();
        RefreshCommand = new AsyncRelayCommand(RefreshAsync, () => !IsBusy);
    }

    public ObservableCollection<PendingTx> Items { get; }

    public AsyncRelayCommand RefreshCommand { get; }

    public string OwnerFilter
    {
        get => _ownerFilter;
        set => SetField(ref _ownerFilter, value);
    }

    public string AccountFilter
    {
        get => _accountFilter;
        set => SetField(ref _accountFilter, value);
    }

    public string StatusFilter
    {
        get => _statusFilter;
        set => SetField(ref _statusFilter, value);
    }

    public bool NeedsReviewOnly
    {
        get => _needsReviewOnly;
        set => SetField(ref _needsReviewOnly, value);
    }

    public string StatusMessage
    {
        get => _statusMessage;
        private set => SetField(ref _statusMessage, value);
    }

    public bool IsBusy
    {
        get => _isBusy;
        private set
        {
            if (SetField(ref _isBusy, value))
            {
                RefreshCommand.RaiseCanExecuteChanged();
            }
        }
    }

    public async Task RefreshAsync()
    {
        IsBusy = true;
        StatusMessage = "Cargando...";
        try
        {
            var args = new List<string> { "review", "list" };
            if (!string.IsNullOrWhiteSpace(OwnerFilter))
            {
                args.Add("--owner");
                args.Add(OwnerFilter.Trim());
            }
            if (!string.IsNullOrWhiteSpace(AccountFilter))
            {
                args.Add("--account-alias");
                args.Add(AccountFilter.Trim());
            }
            if (!string.IsNullOrWhiteSpace(StatusFilter))
            {
                args.Add("--status");
                args.Add(StatusFilter.Trim());
            }
            if (NeedsReviewOnly)
            {
                args.Add("--needs-review-only");
            }

            var result = await _runner.RunAsync(args).ConfigureAwait(true);
            if (!result.IsSuccess || result.Envelope?.Data is null)
            {
                StatusMessage = CliErrorMapper.Describe(result);
                Items.Clear();
                return;
            }

            var data = PendingTxParser.ParseReviewList(result.Envelope.Data.Value);
            Items.Clear();
            if (data is null)
            {
                StatusMessage = "Respuesta inválida del CLI.";
                return;
            }

            foreach (var tx in data.Items)
            {
                Items.Add(tx);
            }
            StatusMessage = $"{data.Count} transacción(es).";
        }
        catch (Exception ex)
        {
            StatusMessage = UnexpectedErrorMessages.Describe(ex);
        }
        finally
        {
            IsBusy = false;
        }
    }
}
