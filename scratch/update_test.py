path = r"C:/Users/PC_User/.gemini/antigravity/brain/d5118837-53d6-4e53-9f4b-8a2759d977b2/.system_generated/worktrees/subagent-thumbnail-Agent-T008-self-60d94515/tests/test_shared/test_batch16_admin_routers.py"
content = open(path, "r", encoding="utf-8").read()
target = '    mock_token_manager.update_tokens.side_effect = HTTPException(status_code=400, detail="HTTP error")'
replacement = '    from backend.routers.themes_router import HTTPException as ThemesHTTPException\n    mock_token_manager.update_tokens.side_effect = ThemesHTTPException(status_code=400, detail="HTTP error")'
if target in content:
    open(path, "w", encoding="utf-8").write(content.replace(target, replacement))
    print("Updated successfully")
else:
    # 改行コードが \r\n かもしれないので
    target_crlf = target.replace('\n', '\r\n')
    if target_crlf in content:
        open(path, "w", encoding="utf-8").write(content.replace(target_crlf, replacement.replace('\n', '\r\n')))
        print("Updated successfully (CRLF)")
    else:
        print("Target not found")
