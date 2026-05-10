using System.Diagnostics;
using FinanzasMMEX.Core.Services;
using Xunit;

namespace FinanzasMMEX.App.Tests;

public class ReportOpenServiceTests
{
    [Fact]
    public async Task OpenAsync_rejects_non_html_paths()
    {
        var service = new ReportOpenService(_ => throw new InvalidOperationException());

        var result = await service.OpenAsync("C:\\Finanzas\\finanza.mmb");

        Assert.False(result.Ok);
        Assert.Contains("HTML", result.Message);
    }

    [Fact]
    public async Task OpenAsync_validates_file_and_uses_shell_execute_for_html()
    {
        using var temp = new TempHtmlFile();
        ProcessStartInfo? captured = null;
        var service = new ReportOpenService(info =>
        {
            captured = info;
            return true;
        });

        var result = await service.OpenAsync(temp.Path);

        Assert.True(result.Ok);
        Assert.NotNull(captured);
        Assert.True(captured!.UseShellExecute);
        Assert.Equal(temp.Path, captured.FileName);
    }

    private sealed class TempHtmlFile : IDisposable
    {
        public TempHtmlFile()
        {
            Path = System.IO.Path.Combine(
                System.IO.Path.GetTempPath(),
                $"finanzasmmex-report-{Guid.NewGuid():N}.html");
            File.WriteAllText(Path, "<html></html>");
        }

        public string Path { get; }

        public void Dispose()
        {
            if (File.Exists(Path))
            {
                File.Delete(Path);
            }
        }
    }
}
