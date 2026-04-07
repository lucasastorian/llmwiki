import pytest

USER_A_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER_A_EMAIL = "alice@test.com"

USER_B_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
USER_B_EMAIL = "bob@test.com"

KB_A_ID = "11111111-1111-1111-1111-111111111111"
KB_B_ID = "22222222-2222-2222-2222-222222222222"

DOC_A_ID = "aaaa1111-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
DOC_B_ID = "bbbb1111-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

CHUNK_A_ID = "cccc1111-cccc-cccc-cccc-cccccccccccc"
CHUNK_B_ID = "dddd1111-dddd-dddd-dddd-dddddddddddd"


@pytest.fixture(autouse=True)
async def seed_two_tenants(pool):
    await pool.execute("DELETE FROM document_chunks")
    await pool.execute("DELETE FROM document_pages")
    await pool.execute("DELETE FROM documents")
    await pool.execute("DELETE FROM api_keys")
    await pool.execute("DELETE FROM knowledge_bases")
    await pool.execute("DELETE FROM users")

    await pool.execute(
        "INSERT INTO users (id, email, display_name) VALUES ($1, $2, 'Alice')",
        USER_A_ID, USER_A_EMAIL,
    )
    await pool.execute(
        "INSERT INTO users (id, email, display_name) VALUES ($1, $2, 'Bob')",
        USER_B_ID, USER_B_EMAIL,
    )

    await pool.execute(
        "INSERT INTO knowledge_bases (id, user_id, name, slug) VALUES ($1, $2, 'Alice KB', 'alice-kb')",
        KB_A_ID, USER_A_ID,
    )
    await pool.execute(
        "INSERT INTO knowledge_bases (id, user_id, name, slug) VALUES ($1, $2, 'Bob KB', 'bob-kb')",
        KB_B_ID, USER_B_ID,
    )

    await pool.execute(
        "INSERT INTO documents (id, knowledge_base_id, user_id, filename, title, path, file_type, status, content, version) "
        "VALUES ($1, $2, $3, 'notes.md', 'Notes', '/wiki/', 'md', 'ready', 'Alice secret content', 1)",
        DOC_A_ID, KB_A_ID, USER_A_ID,
    )
    await pool.execute(
        "INSERT INTO documents (id, knowledge_base_id, user_id, filename, title, path, file_type, status, content, version) "
        "VALUES ($1, $2, $3, 'notes.md', 'Notes', '/wiki/', 'md', 'ready', 'Bob secret content', 1)",
        DOC_B_ID, KB_B_ID, USER_B_ID,
    )

    long_content = "x " * 70
    await pool.execute(
        "INSERT INTO document_chunks (id, document_id, user_id, knowledge_base_id, chunk_index, content, token_count) "
        "VALUES ($1, $2, $3, $4, 0, $5, 35)",
        CHUNK_A_ID, DOC_A_ID, USER_A_ID, KB_A_ID, long_content,
    )
    await pool.execute(
        "INSERT INTO document_chunks (id, document_id, user_id, knowledge_base_id, chunk_index, content, token_count) "
        "VALUES ($1, $2, $3, $4, 0, $5, 35)",
        CHUNK_B_ID, DOC_B_ID, USER_B_ID, KB_B_ID, long_content,
    )

    yield
