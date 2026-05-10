using System.Diagnostics;

namespace FinanzasMMEX.Core.Services;

public interface IReportOpenService
{
    Task<ReportOpenResult> OpenAsync(string? reportPath, CancellationToken cancellationToken = default);
}

public sealed record ReportOpenResult(bool Ok, string Message);

public sealed class ReportOpenService : IReportOpenService
{
    private static readonly HashSet<string> AllowedExtensions =
        new(StringComparer.OrdinalIgnoreCase) { ".html", ".htm" };

    private readonly Func<ProcessStartInfo, bool> _startProcess;

    public ReportOpenService(Func<ProcessStartInfo, bool>? startProcess = null)
    {
        _startProcess = startProcess ?? (info => Process.Start(info) is not null);
    }

    public Task<ReportOpenResult> OpenAsync(
        string? reportPath,
        CancellationToken cancellationToken = default)
    {
        if (cancellationToken.IsCancellationRequested)
        {
            return Task.FromCanceled<ReportOpenResult>(cancellationToken);
        }

        if (string.IsNullOrWhiteSpace(reportPath))
        {
            return Task.FromResult(Fail("No hay reporte HTML para abrir."));
        }

        string fullPath;
        try
        {
            fullPath = Path.GetFullPath(Environment.ExpandEnvironmentVariables(reportPath.Trim()));
        }
        catch (Exception ex) when (ex is ArgumentException or NotSupportedException or PathTooLongException)
        {
            return Task.FromResult(Fail("Ruta de reporte invalida."));
        }

        var extension = Path.GetExtension(fullPath);
        if (!AllowedExtensions.Contains(extension))
        {
            return Task.FromResult(Fail("Solo se pueden abrir reportes HTML."));
        }

        if (!File.Exists(fullPath))
        {
            return Task.FromResult(Fail("El reporte HTML no existe."));
        }

        try
        {
            var started = _startProcess(
                new ProcessStartInfo
                {
                    FileName = fullPath,
                    UseShellExecute = true,
                });
            return Task.FromResult(
                started
                    ? new ReportOpenResult(true, $"Reporte abierto: {fullPath}")
                    : Fail("Windows no pudo abrir el reporte HTML."));
        }
        catch (Exception ex) when (ex is InvalidOperationException or System.ComponentModel.Win32Exception)
        {
            return Task.FromResult(Fail("Windows no pudo abrir el reporte HTML."));
        }
    }

    private static ReportOpenResult Fail(string message) => new(false, message);
}
