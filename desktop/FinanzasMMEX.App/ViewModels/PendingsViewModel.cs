using System.IO;
using System.Collections.ObjectModel;
using System.Text.Json;
using FinanzasMMEX.App.Mvvm;
using FinanzasMMEX.Core.Cli;
using FinanzasMMEX.Core.Models;
using FinanzasMMEX.Core.Services;

namespace FinanzasMMEX.App.ViewModels;

public sealed class PendingsViewModel : ViewModelBase
{
    private readonly ICliRunner _runner;
    private readonly IReportOpenService _reportOpenService;

    private string _ownerFilter = string.Empty;
    private string _accountFilter = string.Empty;
    private string _statusFilter = "pending";
    private string _sinceFilter = string.Empty;
    private string _untilFilter = string.Empty;
    private string _limitFilter = "200";
    private string _sourceFilter = string.Empty;
    private string _categoryFilter = string.Empty;
    private string _merchantFilter = string.Empty;
    private string _reportsDir = string.Empty;
    private string _bulkResolveStatus = "exported";
    private bool _needsReviewOnly;
    private PendingTx? _selectedItem;
    private string _editMerchantNorm = string.Empty;
    private string _editCategoryGuess = string.Empty;
    private string _editSubcategoryGuess = string.Empty;
    private string _editTags = string.Empty;
    private bool _editNeedsReview;
    private string _editReviewReason = string.Empty;
    private string _statusMessage = string.Empty;
    private bool _isBusy;

    public PendingsViewModel(ICliRunner runner, IReportOpenService? reportOpenService = null)
    {
        _runner = runner ?? throw new ArgumentNullException(nameof(runner));
        _reportOpenService = reportOpenService ?? new ReportOpenService();
        Items = new ObservableCollection<PendingTx>();
        RefreshCommand = new AsyncRelayCommand(RefreshAsync, () => !IsBusy);
        SaveSelectedCommand = new AsyncRelayCommand(SaveSelectedAsync, CanSaveSelected);
        BulkClearReviewVisibleCommand = new AsyncRelayCommand(
            BulkClearReviewVisibleAsync,
            () => !IsBusy && Items.Any(item => item.NeedsReview));
        BulkResolveVisibleCommand = new AsyncRelayCommand(
            BulkResolveVisibleAsync,
            () => !IsBusy && Items.Count > 0 && !string.IsNullOrWhiteSpace(BulkResolveStatus));
        OpenLatestReportCommand = new AsyncRelayCommand(OpenLatestReportAsync, () => !IsBusy);
    }

    public ObservableCollection<PendingTx> Items { get; }

    public AsyncRelayCommand RefreshCommand { get; }
    public AsyncRelayCommand SaveSelectedCommand { get; }
    public AsyncRelayCommand BulkClearReviewVisibleCommand { get; }
    public AsyncRelayCommand BulkResolveVisibleCommand { get; }
    public AsyncRelayCommand OpenLatestReportCommand { get; }

    public string OwnerFilter { get => _ownerFilter; set => SetField(ref _ownerFilter, value); }
    public string AccountFilter { get => _accountFilter; set => SetField(ref _accountFilter, value); }
    public string StatusFilter { get => _statusFilter; set => SetField(ref _statusFilter, value); }
    public string SinceFilter { get => _sinceFilter; set => SetField(ref _sinceFilter, value); }
    public string UntilFilter { get => _untilFilter; set => SetField(ref _untilFilter, value); }
    public string SourceFilter { get => _sourceFilter; set => SetField(ref _sourceFilter, value); }
    public string CategoryFilter { get => _categoryFilter; set => SetField(ref _categoryFilter, value); }
    public string MerchantFilter { get => _merchantFilter; set => SetField(ref _merchantFilter, value); }
    public string ReportsDir { get => _reportsDir; set => SetField(ref _reportsDir, value); }

    public string LimitFilter
    {
        get => _limitFilter;
        set => SetField(ref _limitFilter, value);
    }

    public string BulkResolveStatus
    {
        get => _bulkResolveStatus;
        set
        {
            if (SetField(ref _bulkResolveStatus, value))
            {
                BulkResolveVisibleCommand.RaiseCanExecuteChanged();
            }
        }
    }

    public bool NeedsReviewOnly
    {
        get => _needsReviewOnly;
        set => SetField(ref _needsReviewOnly, value);
    }

    public PendingTx? SelectedItem
    {
        get => _selectedItem;
        set
        {
            if (SetField(ref _selectedItem, value))
            {
                LoadEditFields(value);
                SaveSelectedCommand.RaiseCanExecuteChanged();
            }
        }
    }

    public string EditMerchantNorm { get => _editMerchantNorm; set => SetField(ref _editMerchantNorm, value); }
    public string EditCategoryGuess { get => _editCategoryGuess; set => SetField(ref _editCategoryGuess, value); }
    public string EditSubcategoryGuess { get => _editSubcategoryGuess; set => SetField(ref _editSubcategoryGuess, value); }
    public string EditTags { get => _editTags; set => SetField(ref _editTags, value); }
    public bool EditNeedsReview { get => _editNeedsReview; set => SetField(ref _editNeedsReview, value); }
    public string EditReviewReason { get => _editReviewReason; set => SetField(ref _editReviewReason, value); }

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
                RaiseCommandStates();
            }
        }
    }

    public async Task RefreshAsync()
    {
        if (!TryBuildReviewListArgs(out var args))
        {
            Items.Clear();
            return;
        }

        IsBusy = true;
        StatusMessage = "Cargando...";
        try
        {
            var result = await _runner.RunAsync(args).ConfigureAwait(true);
            if (!result.IsSuccess || result.Envelope?.Data is null)
            {
                StatusMessage = CliErrorMapper.Describe(result);
                Items.Clear();
                SelectedItem = null;
                return;
            }

            var data = PendingTxParser.ParseReviewList(result.Envelope.Data.Value);
            Items.Clear();
            if (data is null)
            {
                StatusMessage = "Respuesta invalida del CLI.";
                SelectedItem = null;
                return;
            }

            foreach (var tx in data.Items)
            {
                Items.Add(tx);
            }
            SelectedItem = Items.FirstOrDefault();
            StatusMessage = $"{data.Count} transaccion(es).";
        }
        catch (Exception ex)
        {
            StatusMessage = UnexpectedErrorMessages.Describe(ex);
        }
        finally
        {
            IsBusy = false;
            RaiseCommandStates();
        }
    }

    public async Task SaveSelectedAsync()
    {
        if (SelectedItem is null)
        {
            StatusMessage = "Seleccione una transaccion.";
            return;
        }

        IsBusy = true;
        StatusMessage = "Guardando...";
        try
        {
            var args = new List<string>
            {
                "review",
                "update",
                "--tx-uid",
                SelectedItem.TxUid,
                "--merchant-norm",
                EditMerchantNorm.Trim(),
                "--category-guess",
                EditCategoryGuess.Trim(),
                "--subcategory-guess",
                EditSubcategoryGuess.Trim(),
                "--tags",
                EditTags.Trim(),
                "--needs-review",
                EditNeedsReview ? "true" : "false",
                "--review-reason",
                EditReviewReason.Trim(),
            };

            var result = await _runner.RunAsync(args).ConfigureAwait(true);
            if (!result.IsSuccess || result.Envelope?.Data is null)
            {
                StatusMessage = CliErrorMapper.Describe(result);
                return;
            }

            var data = result.Envelope.Data.Value;
            if (data.TryGetProperty("tx", out var txElement))
            {
                var tx = PendingTxParser.ParsePendingTx(txElement);
                if (tx is not null)
                {
                    ReplaceItem(tx);
                    SelectedItem = tx;
                }
            }
            StatusMessage = "Transaccion actualizada.";
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

    public Task BulkClearReviewVisibleAsync()
    {
        var items = Items
            .Where(item => item.NeedsReview)
            .Select(item => new Dictionary<string, object?>
            {
                ["tx_uid"] = item.TxUid,
                ["needs_review"] = false,
                ["review_reason"] = null,
            })
            .ToList();
        return RunBulkAsync("bulk-update", items);
    }

    public Task BulkResolveVisibleAsync()
    {
        var status = BulkResolveStatus.Trim();
        var items = Items
            .Select(item => new Dictionary<string, object?>
            {
                ["tx_uid"] = item.TxUid,
                ["status"] = status,
            })
            .ToList();
        return RunBulkAsync("bulk-resolve", items);
    }

    public async Task OpenLatestReportAsync()
    {
        IsBusy = true;
        StatusMessage = "Buscando ultimo reporte...";
        try
        {
            var args = new List<string> { "reports", "latest" };
            AddOptionalArg(args, "--reports-dir", ReportsDir);

            var result = await _runner.RunAsync(args).ConfigureAwait(true);
            if (!result.IsSuccess || result.Envelope?.Data is null)
            {
                StatusMessage = CliErrorMapper.Describe(result);
                return;
            }

            var latest = PendingTxParser.ParseLatestReport(result.Envelope.Data.Value);
            if (latest?.Report is null)
            {
                StatusMessage = "No hay reportes HTML generados.";
                return;
            }

            var opened = await _reportOpenService
                .OpenAsync(latest.Report.ReportPath)
                .ConfigureAwait(true);
            StatusMessage = opened.Message;
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

    private async Task RunBulkAsync(
        string action,
        IReadOnlyList<Dictionary<string, object?>> items)
    {
        if (items.Count == 0)
        {
            StatusMessage = "No hay transacciones visibles para actualizar.";
            return;
        }

        IsBusy = true;
        StatusMessage = "Ejecutando lote...";
        var path = Path.Combine(
            Path.GetTempPath(),
            $"finanzasmmex-{action}-{Guid.NewGuid():N}.json");
        try
        {
            var json = JsonSerializer.Serialize(items);
            await File.WriteAllTextAsync(path, json).ConfigureAwait(true);
            var result = await _runner
                .RunAsync(new[] { "review", action, "--input", path })
                .ConfigureAwait(true);
            var bulk = result.Envelope?.Data is null
                ? null
                : PendingTxParser.ParseBulkReview(result.Envelope.Data.Value);

            if (!result.IsSuccess)
            {
                StatusMessage = bulk is null
                    ? CliErrorMapper.Describe(result)
                    : $"{CliErrorMapper.Describe(result)} OK {bulk.ItemsOk}, error {bulk.ItemsError}.";
                return;
            }

            ApplyBulkRows(bulk);
            StatusMessage = bulk is null
                ? "Lote aplicado."
                : $"Lote aplicado: {bulk.ItemsOk}/{bulk.ItemsTotal}.";
        }
        catch (Exception ex)
        {
            StatusMessage = UnexpectedErrorMessages.Describe(ex);
        }
        finally
        {
            TryDelete(path);
            IsBusy = false;
        }
    }

    private bool TryBuildReviewListArgs(out List<string> args)
    {
        args = new List<string> { "review", "list" };
        AddOptionalArg(args, "--owner", OwnerFilter);
        AddOptionalArg(args, "--account-alias", AccountFilter);
        AddOptionalArg(args, "--status", StatusFilter);
        if (NeedsReviewOnly)
        {
            args.Add("--needs-review-only");
        }
        AddOptionalArg(args, "--since", SinceFilter);
        AddOptionalArg(args, "--until", UntilFilter);
        AddOptionalArg(args, "--source-type", SourceFilter);
        AddOptionalArg(args, "--category", CategoryFilter);
        AddOptionalArg(args, "--merchant", MerchantFilter);

        var limitText = LimitFilter.Trim();
        if (!string.IsNullOrWhiteSpace(limitText))
        {
            if (!int.TryParse(limitText, out var limit) || limit < 1)
            {
                StatusMessage = "Limite debe ser un entero mayor que cero.";
                return false;
            }
            args.Add("--limit");
            args.Add(limit.ToString());
        }
        return true;
    }

    private static void AddOptionalArg(List<string> args, string name, string value)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            return;
        }
        args.Add(name);
        args.Add(value.Trim());
    }

    private bool CanSaveSelected() => !IsBusy && SelectedItem is not null;

    private void LoadEditFields(PendingTx? tx)
    {
        EditMerchantNorm = tx?.MerchantNorm ?? string.Empty;
        EditCategoryGuess = tx?.CategoryGuess ?? string.Empty;
        EditSubcategoryGuess = tx?.SubcategoryGuess ?? string.Empty;
        EditTags = tx is null ? string.Empty : string.Join(", ", tx.Tags);
        EditNeedsReview = tx?.NeedsReview ?? false;
        EditReviewReason = tx?.ReviewReason ?? string.Empty;
    }

    private void ReplaceItem(PendingTx tx)
    {
        for (var index = 0; index < Items.Count; index++)
        {
            if (Items[index].TxUid == tx.TxUid)
            {
                Items[index] = tx;
                return;
            }
        }
    }

    private void ApplyBulkRows(BulkReviewData? bulk)
    {
        if (bulk is null)
        {
            return;
        }
        foreach (var row in bulk.Results)
        {
            if (row.Ok && row.Tx is not null)
            {
                ReplaceItem(row.Tx);
            }
        }
        SelectedItem = Items.FirstOrDefault(item => item.TxUid == SelectedItem?.TxUid)
            ?? Items.FirstOrDefault();
    }

    private void RaiseCommandStates()
    {
        RefreshCommand.RaiseCanExecuteChanged();
        SaveSelectedCommand.RaiseCanExecuteChanged();
        BulkClearReviewVisibleCommand.RaiseCanExecuteChanged();
        BulkResolveVisibleCommand.RaiseCanExecuteChanged();
        OpenLatestReportCommand.RaiseCanExecuteChanged();
    }

    private static void TryDelete(string path)
    {
        try
        {
            if (File.Exists(path))
            {
                File.Delete(path);
            }
        }
        catch (IOException)
        {
        }
        catch (UnauthorizedAccessException)
        {
        }
    }
}
