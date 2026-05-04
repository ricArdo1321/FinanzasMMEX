using FinanzasMMEX.App.Mvvm;
using FinanzasMMEX.Core.Cli;
using FinanzasMMEX.Core.Services;

namespace FinanzasMMEX.App.ViewModels;

public sealed class QuickAddViewModel : ViewModelBase
{
    private readonly ICliRunner _runner;

    private string _owner = "ricardo";
    private string _accountAlias = string.Empty;
    private string _amount = string.Empty;
    private string _currency = "CLP";
    private string _direction = "debit";
    private string _date = DateTime.Today.ToString("yyyy-MM-dd");
    private string _merchantRaw = string.Empty;
    private string _categoryGuess = string.Empty;
    private string _statusMessage = string.Empty;
    private bool _isBusy;

    public QuickAddViewModel(ICliRunner runner)
    {
        _runner = runner ?? throw new ArgumentNullException(nameof(runner));
        SubmitCommand = new AsyncRelayCommand(SubmitAsync, CanSubmit);
    }

    public AsyncRelayCommand SubmitCommand { get; }

    public string Owner { get => _owner; set { if (SetField(ref _owner, value)) SubmitCommand.RaiseCanExecuteChanged(); } }
    public string AccountAlias { get => _accountAlias; set { if (SetField(ref _accountAlias, value)) SubmitCommand.RaiseCanExecuteChanged(); } }
    public string Amount { get => _amount; set { if (SetField(ref _amount, value)) SubmitCommand.RaiseCanExecuteChanged(); } }
    public string Currency { get => _currency; set => SetField(ref _currency, value); }
    public string Direction { get => _direction; set => SetField(ref _direction, value); }
    public string Date { get => _date; set { if (SetField(ref _date, value)) SubmitCommand.RaiseCanExecuteChanged(); } }
    public string MerchantRaw { get => _merchantRaw; set { if (SetField(ref _merchantRaw, value)) SubmitCommand.RaiseCanExecuteChanged(); } }
    public string CategoryGuess { get => _categoryGuess; set => SetField(ref _categoryGuess, value); }

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
                SubmitCommand.RaiseCanExecuteChanged();
            }
        }
    }

    private bool CanSubmit() =>
        !IsBusy
        && !string.IsNullOrWhiteSpace(AccountAlias)
        && !string.IsNullOrWhiteSpace(Amount)
        && !string.IsNullOrWhiteSpace(MerchantRaw)
        && !string.IsNullOrWhiteSpace(Date);

    public async Task SubmitAsync()
    {
        IsBusy = true;
        StatusMessage = "Enviando...";
        try
        {
            var args = new List<string>
            {
                "quickadd", "create",
                "--owner", Owner,
                "--account-alias", AccountAlias,
                "--amount", Amount,
                "--currency", Currency,
                "--direction", Direction,
                "--date", Date,
                "--merchant-raw", MerchantRaw,
            };
            if (!string.IsNullOrWhiteSpace(CategoryGuess))
            {
                args.Add("--category-guess");
                args.Add(CategoryGuess);
            }

            var result = await _runner.RunAsync(args).ConfigureAwait(true);
            if (!result.IsSuccess)
            {
                StatusMessage = CliErrorMapper.Describe(result);
                return;
            }

            var warnings = result.Envelope?.Warnings ?? Array.Empty<string>();
            StatusMessage = warnings.Count > 0
                ? $"OK: {string.Join("; ", warnings)}"
                : "Transacción creada.";
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
