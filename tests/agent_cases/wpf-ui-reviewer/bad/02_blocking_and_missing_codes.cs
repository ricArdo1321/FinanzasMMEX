// BAD: .Result blocks UI; only exit code 0 handled (2/3/4/5 ignored);
// raw error.details exposed to user; no INotifyPropertyChanged on ViewModel.
using System.Diagnostics;
using System.Text.Json;
using System.Threading.Tasks;
using System.Windows;

namespace FinanzasMMEX.App.ViewModels;

public sealed class RunViewModel
{
    public string? Status { get; set; }  // VIOLATION: no INotifyPropertyChanged

    public void Run()
    {
        var psi = new ProcessStartInfo("finanzasmmex", "run --source all")
        {
            RedirectStandardOutput = true,
            UseShellExecute = false,
        };
        var p = Process.Start(psi)!;
        var output = p.StandardOutput.ReadToEndAsync().Result;  // VIOLATION
        p.WaitForExit();  // VIOLATION: sync on UI thread

        if (p.ExitCode == 0)
        {
            Status = "OK";
            return;
        }
        // VIOLATION: exit codes 2, 3, 4, 5 not distinguished.
        var env = JsonSerializer.Deserialize<JsonElement>(output);
        var details = env.GetProperty("errors")[0].GetProperty("details").ToString();
        MessageBox.Show(details);  // VIOLATION: raw details exposed
    }
}
