using System.Windows;
using FinanzasMMEX.App.ViewModels;
using FinanzasMMEX.Core.Cli;

namespace FinanzasMMEX.App;

public partial class MainWindow : Window
{
    public MainWindow()
        : this(new MainViewModel(new CliRunner()))
    {
    }

    public MainWindow(MainViewModel viewModel)
    {
        InitializeComponent();
        DataContext = viewModel;
    }
}
