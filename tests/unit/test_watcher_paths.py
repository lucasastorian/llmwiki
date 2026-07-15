from pathlib import PurePosixPath, PureWindowsPath

from domain.watcher import _get_source_kind, _workspace_relative


class TestWorkspaceRelative:
    def test_windows_paths_normalize_to_forward_slashes(self):
        relative = _workspace_relative(
            PureWindowsPath(r"C:\ws\wiki\concepts\attention.md"),
            PureWindowsPath(r"C:\ws"),
        )
        assert relative == "wiki/concepts/attention.md"

    def test_posix_paths_unchanged(self):
        relative = _workspace_relative(
            PurePosixPath("/ws/wiki/overview.md"),
            PurePosixPath("/ws"),
        )
        assert relative == "wiki/overview.md"

    def test_windows_wiki_page_classified_as_wiki(self):
        relative = _workspace_relative(
            PureWindowsPath(r"C:\ws\wiki\overview.md"),
            PureWindowsPath(r"C:\ws"),
        )
        assert _get_source_kind(relative) == "wiki"

    def test_source_file_classified_as_source(self):
        assert _get_source_kind("papers/paper.pdf") == "source"
