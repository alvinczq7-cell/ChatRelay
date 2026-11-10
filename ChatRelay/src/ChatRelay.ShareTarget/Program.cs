using System.Diagnostics;
using System.Text;
using System.Text.Json;
using Windows.ApplicationModel;
using Windows.ApplicationModel.Activation;
using Windows.ApplicationModel.DataTransfer;
using Windows.ApplicationModel.DataTransfer.ShareTarget;
using Windows.Storage;

namespace ChatRelay.ShareTarget;

/// <summary>
/// Minimal Windows share target. When WeChat's 合并转发 → 其他应用 hands over a
/// chat archive, every shared item is copied into
/// %LOCALAPPDATA%\ChatRelay\Inbox\&lt;timestamp&gt;\ together with a manifest.json,
/// and the folder is opened in Explorer. Nothing is uploaded anywhere.
/// </summary>
internal static class Program
{
    private static readonly string Root = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "ChatRelay");
    private static readonly string InboxRoot = Path.Combine(Root, "Inbox");
    private static readonly string LogPath = Path.Combine(Root, "relay.log");

    [STAThread]
    private static int Main(string[] args)
    {
        Directory.CreateDirectory(InboxRoot);
        try
        {
            if (args.Contains("--registration-check"))
            {
                Log($"registration-check: hasIdentity={HasPackageIdentity()}");
                return HasPackageIdentity() ? 0 : 2;
            }

            var activation = AppInstance.GetActivatedEventArgs();
            Log($"activated: kind={activation?.Kind.ToString() ?? "none"}");

            if (activation is ShareTargetActivatedEventArgs share)
            {
                var dir = HandleShareAsync(share.ShareOperation).GetAwaiter().GetResult();
                OpenInExplorer(dir);
                return 0;
            }

            // Launched directly (not via share): just show the inbox.
            OpenInExplorer(InboxRoot);
            return 0;
        }
        catch (Exception error)
        {
            Log("fatal: " + error);
            return 1;
        }
    }

    private static async Task<string> HandleShareAsync(ShareOperation op)
    {
        var stamp = DateTime.Now.ToString("yyyyMMdd-HHmmss");
        var dir = Path.Combine(InboxRoot, stamp);
        for (var n = 2; Directory.Exists(dir); n++) dir = Path.Combine(InboxRoot, $"{stamp}-{n}");
        Directory.CreateDirectory(dir);

        TryReport(op.ReportStarted, "ReportStarted");

        var data = op.Data;
        var formats = data.AvailableFormats.ToList();
        Log($"share received -> {dir}; formats=[{string.Join(", ", formats)}]");

        var saved = new List<object>();
        var errors = new List<string>();

        if (data.Contains(StandardDataFormats.StorageItems))
        {
            try
            {
                var items = await data.GetStorageItemsAsync();
                foreach (var item in items)
                {
                    try { saved.AddRange(await CopyItemAsync(item, dir)); }
                    catch (Exception e) { errors.Add($"item {item.Name}: {e.Message}"); Log($"copy failed {item.Name}: {e}"); }
                }
            }
            catch (Exception e) { errors.Add("StorageItems: " + e.Message); Log("StorageItems failed: " + e); }
        }

        if (data.Contains(StandardDataFormats.Text))
        {
            try
            {
                var text = await data.GetTextAsync();
                var path = Path.Combine(dir, "shared-text.txt");
                await File.WriteAllTextAsync(path, text, new UTF8Encoding(false));
                saved.Add(Describe(path, dir, "Text"));
            }
            catch (Exception e) { errors.Add("Text: " + e.Message); }
        }

        if (data.Contains(StandardDataFormats.WebLink) || data.Contains(StandardDataFormats.Uri))
        {
            try
            {
                var uri = data.Contains(StandardDataFormats.WebLink)
                    ? await data.GetWebLinkAsync()
                    : await data.GetUriAsync();
                var path = Path.Combine(dir, "shared-link.txt");
                await File.WriteAllTextAsync(path, uri.ToString(), new UTF8Encoding(false));
                saved.Add(Describe(path, dir, "Uri"));
            }
            catch (Exception e) { errors.Add("Uri: " + e.Message); }
        }

        if (data.Contains(StandardDataFormats.Bitmap))
        {
            try
            {
                var reference = await data.GetBitmapAsync();
                using var stream = await reference.OpenReadAsync();
                var path = Path.Combine(dir, "shared-bitmap.png");
                await using (var file = File.Create(path))
                    await stream.AsStreamForRead().CopyToAsync(file);
                saved.Add(Describe(path, dir, "Bitmap"));
            }
            catch (Exception e) { errors.Add("Bitmap: " + e.Message); }
        }

        var manifest = new
        {
            receivedAt = DateTimeOffset.Now,
            sourceAppName = SafeGet(() => data.Properties.ApplicationName),
            sourcePackage = SafeGet(() => data.Properties.PackageFamilyName),
            title = SafeGet(() => data.Properties.Title),
            formats,
            files = saved,
            errors,
        };
        await File.WriteAllTextAsync(
            Path.Combine(dir, "manifest.json"),
            JsonSerializer.Serialize(manifest, new JsonSerializerOptions
            {
                WriteIndented = true,
                Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
            }),
            new UTF8Encoding(false));

        Log($"saved {saved.Count} item(s), {errors.Count} error(s)");

        // The sharing app (WeChat) waits on these; always release it.
        TryReport(op.ReportDataRetrieved, "ReportDataRetrieved");
        TryReport(op.ReportCompleted, "ReportCompleted");
        return dir;
    }

    private static async Task<List<object>> CopyItemAsync(IStorageItem item, string dir)
    {
        var result = new List<object>();
        if (item is StorageFile file)
        {
            var dest = UniquePath(Path.Combine(dir, SafeName(file.Name)));
            if (!string.IsNullOrEmpty(file.Path) && File.Exists(file.Path))
            {
                File.Copy(file.Path, dest);
            }
            else
            {
                // Virtual / brokered file without a real path.
                var folder = await StorageFolder.GetFolderFromPathAsync(dir);
                var copy = await file.CopyAsync(folder, Path.GetFileName(dest), NameCollisionOption.GenerateUniqueName);
                dest = copy.Path;
            }
            result.Add(Describe(dest, dir, "StorageItems", file.Path));
        }
        else if (item is StorageFolder folder && Directory.Exists(folder.Path))
        {
            var destRoot = UniquePath(Path.Combine(dir, SafeName(folder.Name)));
            foreach (var src in Directory.EnumerateFiles(folder.Path, "*", SearchOption.AllDirectories))
            {
                var dest = Path.Combine(destRoot, Path.GetRelativePath(folder.Path, src));
                Directory.CreateDirectory(Path.GetDirectoryName(dest)!);
                File.Copy(src, dest);
                result.Add(Describe(dest, dir, "StorageItems", src));
            }
        }
        return result;
    }

    private static object Describe(string path, string dir, string format, string? originalPath = null) => new
    {
        name = Path.GetRelativePath(dir, path),
        bytes = new FileInfo(path).Length,
        format,
        originalPath,
    };

    private static string SafeName(string name)
    {
        foreach (var c in Path.GetInvalidFileNameChars()) name = name.Replace(c, '_');
        return string.IsNullOrWhiteSpace(name) || name is "." or ".." ? "item" : name;
    }

    private static string UniquePath(string path)
    {
        if (!File.Exists(path) && !Directory.Exists(path)) return path;
        var stem = Path.GetFileNameWithoutExtension(path);
        var ext = Path.GetExtension(path);
        var parent = Path.GetDirectoryName(path)!;
        for (var n = 2; ; n++)
        {
            var candidate = Path.Combine(parent, $"{stem} ({n}){ext}");
            if (!File.Exists(candidate) && !Directory.Exists(candidate)) return candidate;
        }
    }

    private static bool HasPackageIdentity()
    {
        try { return Package.Current?.Id?.Name is not null; }
        catch { return false; }
    }

    private static void TryReport(Action report, string name)
    {
        try { report(); }
        catch (Exception e) { Log($"{name} ignored: {e.Message}"); }
    }

    private static string? SafeGet(Func<string?> get)
    {
        try { return get(); } catch { return null; }
    }

    private static void OpenInExplorer(string dir)
    {
        try { Process.Start(new ProcessStartInfo("explorer.exe", $"\"{dir}\"") { UseShellExecute = true }); }
        catch (Exception e) { Log("explorer failed: " + e.Message); }
    }

    private static void Log(string message)
    {
        try
        {
            Directory.CreateDirectory(Root);
            File.AppendAllText(LogPath, $"{DateTimeOffset.Now:O} {message}{Environment.NewLine}", new UTF8Encoding(false));
        }
        catch { /* logging must never break a share */ }
    }
}
