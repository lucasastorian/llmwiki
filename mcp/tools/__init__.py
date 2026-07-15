def register(mcp, get_user_id, fs_factory) -> None:
    from .guide import register as register_guide
    from .list import register as register_list
    from .search import register as register_search
    from .read import register as register_read
    from .write import register as register_write
    from .delete import register as register_delete
    from .lint import register as register_lint
    from .reply import register as register_reply
    from .comments import register as register_comments

    register_guide(mcp, get_user_id, fs_factory)
    register_list(mcp, get_user_id, fs_factory)
    register_search(mcp, get_user_id, fs_factory)
    register_read(mcp, get_user_id, fs_factory)
    register_write(mcp, get_user_id, fs_factory)
    register_delete(mcp, get_user_id, fs_factory)
    register_lint(mcp, get_user_id, fs_factory)
    register_reply(mcp, get_user_id, fs_factory)
    register_comments(mcp, get_user_id, fs_factory)
