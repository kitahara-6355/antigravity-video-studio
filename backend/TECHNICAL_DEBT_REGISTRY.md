# Technical Debt Registry — Antigravity Pipeline

> **最終更新**: 2026-07-27 07:35
> **総エントリ数**: 1461 (open: 470 / fixed: 841)
> **管理方式**: JSON+Markdown二重管理（VF同型）。手動編集禁止。API経由で更新。
> **更新ルール**: 新規 `except Exception` 追加時は `register_debt()` API経由で登録必須

---

## カテゴリ別サマリー

| カテゴリ | 意味 | Total | Open | Fixed | Accepted |
|:---|:---|:---:|:---:|:---:|:---:|
| CRITICAL_ROUTER | Router層 HTTPException捕捉バグ | 244 | 0 | 218 | 26 |
| CRITICAL_PHASE4 | Phase 4直接干渉 | 37 | 0 | 35 | 2 |
| IMPORTANT_SERVICE | Service/Engine層 | 388 | 156 | 200 | 32 |
| MINOR_INFRA | インフラ層（ログ出力あり） | 640 | 257 | 333 | 50 |
| ACCEPTED_SAFETY | 正当な安全ネット（修正不要） | 152 | 57 | 55 | 40 |

---

## CRITICAL_ROUTER: Router層 HTTPException捕捉バグ (244件 / open:0 fixed:218)

| ID | ファイル | 行 | ステータス | パターン | 修正パターン | 修正日 |
|:--|:---|:---:|:---:|:---|:---|:---|
| TD-001 | `agents/director.py` | L103 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-23 |
| TD-002 | `routers/ab_test_tracker.py` | L111 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-003 | `routers/ab_test_tracker.py` | L161 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-004 | `routers/ab_test_tracker.py` | L181 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-005 | `routers/ab_test_tracker.py` | L198 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-006 | `routers/admin_setup_router.py` | L103 | ✅ fixed | `except Exception:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-007 | `routers/admin_setup_router.py` | L183 | ✅ fixed | `except Exception:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-008 | `routers/admin_setup_router.py` | L207 | ✅ fixed | `except Exception:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-009 | `routers/admin_setup_router.py` | L227 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-010 | `routers/admin_setup_router.py` | L286 | ✅ fixed | `except Exception:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-011 | `routers/admin_setup_router.py` | L301 | ✅ fixed | `except Exception:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-012 | `routers/admin_setup_router.py` | L340 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-013 | `routers/admin_setup_router.py` | L387 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-014 | `routers/admin_setup_router.py` | L412 | ✅ fixed | `except Exception:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-015 | `routers/admin_setup_router.py` | L537 | ✅ fixed | `except Exception:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-016 | `routers/approval_router.py` | L67 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-017 | `routers/approval_router.py` | L88 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-018 | `routers/approval_router.py` | L102 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-019 | `routers/dashboard_router.py` | L96 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-23 |
| TD-020 | `routers/health.py` | L38 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-23 |
| TD-021 | `routers/health.py` | L71 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-23 |
| TD-022 | `routers/health.py` | L138 | ✅ fixed | `except Exception:` | `except HTTPException: raise` を追加 | 2026-05-23 |
| TD-023 | `routers/health.py` | L143 | ✅ fixed | `except Exception:` | `except HTTPException: raise` を追加 | 2026-05-23 |
| TD-024 | `routers/health.py` | L153 | ✅ fixed | `except Exception:` | `except HTTPException: raise` を追加 | 2026-06-01 |
| TD-025 | `routers/legacy_council_router.py` | L33 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-026 | `routers/legacy_council_router.py` | L45 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-027 | `routers/legacy_council_router.py` | L69 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-028 | `routers/legacy_director_router.py` | L95 | ✅ fixed | `except Exception:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-029 | `routers/legacy_director_router.py` | L108 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-030 | `routers/legacy_director_router.py` | L122 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-031 | `routers/legacy_live_websocket.py` | L42 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-23 |
| TD-032 | `routers/legacy_live_websocket.py` | L58 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-23 |
| TD-033 | `routers/legacy_live_websocket.py` | L72 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-23 |
| TD-034 | `routers/legacy_management_router.py` | L102 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-035 | `routers/legacy_management_router.py` | L133 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-036 | `routers/legacy_management_router.py` | L162 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-037 | `routers/legacy_management_router.py` | L206 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-038 | `routers/legacy_management_router.py` | L216 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-039 | `routers/legacy_management_router.py` | L239 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-040 | `routers/legacy_management_router.py` | L282 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-041 | `routers/legacy_production_router.py` | L133 | ✅ fixed | `except Exception:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-042 | `routers/legacy_production_router.py` | L158 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-043 | `routers/legacy_production_router.py` | L200 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-044 | `routers/legacy_production_router.py` | L217 | ✅ fixed | `except Exception:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-045 | `routers/legacy_production_router.py` | L277 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-046 | `routers/legacy_production_router.py` | L302 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-047 | `routers/legacy_production_router.py` | L327 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-048 | `routers/legacy_production_router.py` | L342 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-049 | `routers/legacy_production_router.py` | L356 | ✅ fixed | `except Exception:` | `except HTTPException: raise` を追加 | 2026-05-23 |
| TD-050 | `routers/legacy_production_router.py` | L379 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-051 | `routers/legacy_production_router.py` | L417 | ✅ fixed | `except Exception:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-052 | `routers/legacy_production_router.py` | L421 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-053 | `routers/legacy_production_router.py` | L466 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-054 | `routers/philosophy_router.py` | L54 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-055 | `routers/philosophy_router.py` | L79 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-056 | `routers/philosophy_router.py` | L96 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-057 | `routers/pipeline_report.py` | L39 | ✅ fixed | `except Exception:` | `except HTTPException: raise` を追加 | 2026-05-23 |
| TD-058 | `routers/pipeline_report.py` | L60 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-23 |
| TD-059 | `routers/pipeline_router.py` | L116 | ✅ fixed | `except Exception:` | `except HTTPException: raise` を追加 | 2026-05-22 |
| TD-060 | `routers/pipeline_router.py` | L150 | ✅ fixed | `except Exception:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-061 | `routers/pipeline_router.py` | L289 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-062 | `routers/pipeline_router.py` | L329 | ✅ fixed | `except Exception:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-063 | `routers/pipeline_router.py` | L422 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-064 | `routers/pipeline_router.py` | L505 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-065 | `routers/pipeline_router.py` | L568 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-066 | `routers/pipeline_router.py` | L703 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-067 | `routers/pipeline_router.py` | L729 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-068 | `routers/pipeline_router.py` | L739 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-069 | `routers/pipeline_router.py` | L756 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-12 |
| TD-070 | `routers/pipeline_router.py` | L769 | ✅ fixed | `except Exception:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-071 | `routers/pipeline_router.py` | L881 | ✅ fixed | `except Exception as _vram_err:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-072 | `routers/pipeline_router.py` | L1070 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-073 | `routers/pipeline_router.py` | L1094 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-22 |
| TD-074 | `routers/preview.py` | L87 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-075 | `routers/preview.py` | L137 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-076 | `routers/preview.py` | L159 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-077 | `routers/review_router.py` | L136 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-078 | `routers/review_router.py` | L160 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-079 | `routers/review_router.py` | L188 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-080 | `routers/review_router.py` | L215 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-081 | `routers/review_router.py` | L240 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-082 | `routers/shorts.py` | L56 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-083 | `routers/shorts.py` | L99 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-084 | `routers/shorts.py` | L118 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-085 | `routers/shorts.py` | L154 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-086 | `routers/shorts.py` | L258 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-087 | `routers/smartcut.py` | L103 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-088 | `routers/smartcut.py` | L208 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-089 | `routers/soul_router.py` | L37 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-22 |
| TD-090 | `routers/soul_router.py` | L242 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-091 | `routers/themes_router.py` | L455 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-092 | `routers/themes_router.py` | L493 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-093 | `routers/themes_router.py` | L545 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-094 | `routers/themes_router.py` | L589 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-095 | `routers/themes_router.py` | L677 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-096 | `routers/usage_router.py` | L76 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-097 | `routers/usage_router.py` | L147 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-098 | `routers/usage_router.py` | L203 | ✅ fixed | `except Exception:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-099 | `routers/usage_router.py` | L311 | ✅ fixed | `except Exception:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-100 | `routers/usage_router.py` | L487 | ✅ fixed | `except Exception:` | `except HTTPException: raise` を追加 | 2026-06-13 |
| TD-101 | `routers/usage_router.py` | L499 | ✅ fixed | `except Exception:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-1010 | `routers/segments.py` | L68 | ✅ fixed | `except Exception as e:` | HTTPExceptionへの適切な変換 | 2026-06-05 |
| TD-1011 | `routers/segments.py` | L108 | ✅ fixed | `except Exception as e:` | HTTPExceptionへの適切な変換 | 2026-06-13 |
| TD-1012 | `routers/segments.py` | L47 | ✅ fixed | `except Exception as e:` | HTTPExceptionへの適切な変換 | 2026-06-05 |
| TD-1014 | `routers/segments.py` | L54 | ✅ fixed | `except Exception as e:` | HTTPExceptionへの適切な変換 | 2026-06-05 |
| TD-1015 | `routers/segments.py` | L76 | ✅ fixed | `except Exception as e:` | HTTPExceptionへの適切な変換 | 2026-06-05 |
| TD-1016 | `routers/segments.py` | L111 | ✅ fixed | `except Exception as e:` | HTTPExceptionへの適切な変換 | 2026-06-05 |
| TD-1017 | `routers/segments.py` | L167 | ✅ fixed | `except Exception as e:` | HTTPExceptionへの適切な変換 | 2026-06-05 |
| TD-102 | `routers/usage_router.py` | L535 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-103 | `routers/usage_router.py` | L544 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-104 | `routers/websocket.py` | L41 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-23 |
| TD-105 | `routers/websocket.py` | L112 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-23 |
| TD-106 | `routers/websocket.py` | L126 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-23 |
| TD-107 | `routers/youtube_optimizer.py` | L138 | ✅ fixed | `except Exception:` | `except HTTPException: raise` を追加 | 2026-05-29 |
| TD-108 | `routers/youtube_optimizer.py` | L192 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-109 | `routers/youtube_optimizer.py` | L318 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-110 | `routers/youtube_optimizer.py` | L355 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-111 | `routers/youtube_optimizer.py` | L398 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-112 | `routers/youtube_optimizer.py` | L438 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-113 | `routers/youtube_optimizer.py` | L463 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-114 | `routers/youtube_optimizer.py` | L476 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-115 | `routers/youtube_optimizer.py` | L489 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-116 | `routers/youtube_optimizer.py` | L565 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-117 | `routers/youtube_optimizer.py` | L636 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-118 | `routers/youtube_optimizer.py` | L674 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-119 | `routers/youtube_optimizer.py` | L704 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-120 | `routers/youtube_optimizer.py` | L727 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-121 | `routers/youtube_optimizer.py` | L749 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-1210 | `routers/health.py` | L266 | ✅ fixed | `except Exception as e` | HTTPException translation | 2026-06-07 |
| TD-122 | `routers/youtube_optimizer.py` | L765 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-123 | `routers/youtube_optimizer.py` | L787 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-124 | `routers/youtube_optimizer.py` | L811 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-125 | `routers/youtube_optimizer.py` | L861 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-126 | `routers/youtube_optimizer.py` | L894 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-127 | `routers/youtube_optimizer.py` | L906 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-1277 | `routers/themes_router.py` | L639 | ✅ fixed | `except Exception as e:` | HTTPExceptionへの適切な変換 | 2026-06-13 |
| TD-1278 | `routers/themes_router.py` | L700 | ✅ fixed | `except Exception as e:` | HTTPExceptionへの適切な変換 | 2026-06-13 |
| TD-1279 | `routers/themes_router.py` | L310 | ✅ fixed | `except Exception as e:` | HTTPExceptionへの適切な変換 | 2026-06-13 |
| TD-128 | `routers/youtube_optimizer.py` | L917 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-1280 | `routers/themes_router.py` | L366 | ✅ fixed | `except Exception as e:` | HTTPExceptionへの適切な変換 | 2026-06-13 |
| TD-1281 | `routers/themes_router.py` | L193 | ✅ fixed | `except Exception as e:` | HTTPExceptionへの適切な変換 | 2026-06-13 |
| TD-1282 | `routers/themes_router.py` | L449 | ✅ fixed | `except Exception as e:` | HTTPExceptionへの適切な変換 | 2026-06-13 |
| TD-129 | `routers/youtube_optimizer.py` | L928 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-1290 | `routers/health.py` | L306 | ✅ fixed | `broad_except` | HTTPException translation | 2026-06-13 |
| TD-1291 | `routers/health.py` | L309 | ✅ fixed | `broad_except` | HTTPException translation | 2026-06-13 |
| TD-130 | `routers/youtube_optimizer.py` | L943 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-131 | `routers/youtube_optimizer.py` | L964 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-132 | `routers/youtube_optimizer.py` | L981 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-133 | `routers/youtube_optimizer.py` | L998 | 🔵 accepted | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-06-13 |
| TD-134 | `routers/youtube_optimizer.py` | L1018 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-135 | `routers/youtube_optimizer.py` | L1044 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-136 | `routers/youtube_optimizer.py` | L1055 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-137 | `routers/youtube_optimizer.py` | L1085 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-138 | `routers/youtube_upload.py` | L59 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-1386 | `routers/youtube_upload.py` | L94 | ✅ fixed | `except Exception as e:` | except HTTPException: raise を前行に配置 | 2026-06-14 |
| TD-1387 | `routers/youtube_upload.py` | L134 | ✅ fixed | `except Exception as e:` | except HTTPException: raise を前行に配置した上で一元ハンドラー呼び出し | 2026-06-15 |
| TD-1388 | `routers/youtube_upload.py` | L178 | ✅ fixed | `except Exception as e:` | except HTTPException: raise を前行に配置した上で一元ハンドラー呼び出し | 2026-06-15 |
| TD-1389 | `routers/youtube_upload.py` | L278 | ✅ fixed | `except Exception as e:` | except HTTPException: raise を前行に配置した上で一元ハンドラー呼び出し | 2026-06-15 |
| TD-139 | `routers/youtube_upload.py` | L84 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-1390 | `routers/youtube_upload.py` | L306 | ✅ fixed | `except Exception as e:` | except HTTPException: raise を前行に配置した上で一元ハンドラー呼び出し | 2026-06-15 |
| TD-1391 | `routers/youtube_upload.py` | L135 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を前行に追加して再スロー | 2026-06-15 |
| TD-1392 | `routers/youtube_upload.py` | L179 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を前行に追加して再スロー | 2026-06-15 |
| TD-1393 | `routers/youtube_upload.py` | L279 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を前行に追加して再スロー | 2026-06-15 |
| TD-1394 | `routers/youtube_upload.py` | L307 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を前行に追加して再スロー | 2026-06-15 |
| TD-140 | `routers/youtube_upload.py` | L125 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-1405 | `routers/admin_quality_router.py` | L211 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-06-23 |
| TD-1406 | `routers/admin_quality_router.py` | L225 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-06-23 |
| TD-1407 | `routers/admin_quality_router.py` | L239 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-06-23 |
| TD-1408 | `routers/admin_quality_router.py` | L263 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-06-23 |
| TD-1409 | `routers/admin_quality_router.py` | L283 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-06-23 |
| TD-141 | `routers/youtube_upload.py` | L144 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-05-10 |
| TD-1410 | `routers/admin_quality_router.py` | L297 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-06-23 |
| TD-1411 | `routers/admin_quality_router.py` | L311 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-06-23 |
| TD-1412 | `routers/admin_quality_router.py` | L325 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-06-23 |
| TD-1413 | `routers/admin_quality_router.py` | L339 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-06-23 |
| TD-1414 | `routers/admin_quality_router.py` | L353 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-06-23 |
| TD-1415 | `routers/admin_quality_router.py` | L378 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-06-23 |
| TD-1416 | `routers/admin_quality_router.py` | L406 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-06-23 |
| TD-1417 | `routers/admin_quality_router.py` | L427 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-06-23 |
| TD-1418 | `routers/admin_quality_router.py` | L449 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-06-23 |
| TD-1419 | `routers/admin_quality_router.py` | L470 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-06-23 |
| TD-1420 | `routers/admin_quality_router.py` | L491 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-06-23 |
| TD-1421 | `routers/admin_quality_router.py` | L505 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-06-23 |
| TD-1422 | `routers/admin_quality_router.py` | L527 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-06-23 |
| TD-1423 | `routers/admin_quality_router.py` | L550 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-06-23 |
| TD-1424 | `routers/admin_quality_router.py` | L564 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-06-23 |
| TD-1425 | `routers/admin_quality_router.py` | L580 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-06-23 |
| TD-1426 | `routers/admin_quality_router.py` | L594 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-06-23 |
| TD-1427 | `routers/admin_quality_router.py` | L611 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-06-23 |
| TD-1428 | `routers/admin_quality_router.py` | L625 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-06-23 |
| TD-1429 | `routers/admin_quality_router.py` | L647 | ✅ fixed | `except Exception as e:` | `except HTTPException: raise` を追加 | 2026-06-23 |
| TD-697 | `routers/director.py` | L27 | 🔵 accepted | `except Exception as e:` | HTTPException translation | 2026-05-22 |
| TD-698 | `routers/director.py` | L77 | 🔵 accepted | `except Exception as e:` | HTTPException translation | 2026-05-22 |
| TD-699 | `routers/director.py` | L93 | 🔵 accepted | `except Exception as e:` | HTTPException translation | 2026-05-22 |
| TD-700 | `routers/director.py` | L110 | 🔵 accepted | `except Exception as e:` | HTTPException translation | 2026-05-22 |
| TD-701 | `routers/director.py` | L123 | 🔵 accepted | `except Exception as e:` | HTTPException translation | 2026-05-22 |
| TD-702 | `routers/director.py` | L144 | 🔵 accepted | `except Exception as e:` | HTTPException translation | 2026-05-22 |
| TD-703 | `routers/director.py` | L165 | 🔵 accepted | `except Exception as e:` | HTTPException translation | 2026-05-22 |
| TD-704 | `routers/director.py` | L186 | 🔵 accepted | `except Exception as e:` | HTTPException translation | 2026-05-22 |
| TD-705 | `routers/director.py` | L215 | 🔵 accepted | `except Exception as xp_err:` | HTTPException translation | 2026-05-22 |
| TD-706 | `routers/director.py` | L223 | 🔵 accepted | `except Exception as e:` | HTTPException translation | 2026-05-22 |
| TD-707 | `routers/director.py` | L246 | 🔵 accepted | `except Exception as e:` | HTTPException translation | 2026-05-22 |
| TD-708 | `routers/director.py` | L265 | 🔵 accepted | `except Exception as e:` | HTTPException translation | 2026-05-22 |
| TD-823 | `routers/themes_router.py` | L679 | ✅ fixed | `except Exception as e:` | HTTPExceptionへの適切な変換 | 2026-06-13 |
| TD-824 | `routers/themes_router.py` | L730 | ✅ fixed | `except Exception as e:` | HTTPExceptionへの適切な変換 | 2026-06-13 |
| TD-825 | `routers/themes_router.py` | L756 | ✅ fixed | `except Exception as e:` | HTTPExceptionへの適切な変換 | 2026-06-13 |
| TD-835 | `api_versioning.py` | L72 | ✅ fixed | `except Exception as e:` | except HTTPException: raise を前行に配置 | 2026-06-13 |
| TD-836 | `api_versioning.py` | L73 | ✅ fixed | `except Exception` | except HTTPException: raise を前行に配置 | 2026-06-13 |
| TD-837 | `api_versioning.py` | L80 | 🔵 accepted | `except Exception` | except HTTPException: raise を前行に配置 | 2026-06-13 |
| TD-838 | `api_versioning.py` | L81 | 🔵 accepted | `except Exception` | except HTTPException: raise を前行に配置 | 2026-06-13 |
| TD-839 | `api_versioning.py` | L88 | 🔵 accepted | `except Exception as tdr_err:` | except HTTPException: raise を前行に配置 | 2026-06-13 |
| TD-840 | `api_versioning.py` | L119 | ✅ fixed | `except Exception as e:` | except HTTPException: raise を前行に配置 | 2026-06-13 |
| TD-841 | `api_versioning.py` | L120 | ✅ fixed | `except Exception` | except HTTPException: raise を前行に配置 | 2026-06-13 |
| TD-842 | `api_versioning.py` | L127 | 🔵 accepted | `except Exception` | except HTTPException: raise を前行に配置 | 2026-06-13 |
| TD-843 | `api_versioning.py` | L128 | 🔵 accepted | `except Exception` | except HTTPException: raise を前行に配置 | 2026-06-13 |
| TD-844 | `api_versioning.py` | L135 | 🔵 accepted | `except Exception as tdr_err:` | except HTTPException: raise を前行に配置 | 2026-06-13 |
| TD-865 | `routers/themes_router.py` | L674 | ✅ fixed | `except Exception as e:` | HTTPExceptionへの適切な変換 | 2026-06-13 |
| TD-890 | `routers/render.py` | L558 | ✅ fixed | `except Exception as e:` | except HTTPException: raise を追加済み | 2026-06-13 |
| TD-891 | `routers/render.py` | L570 | ✅ fixed | `except Exception as e:` | except HTTPException: raise を追加済み | 2026-06-13 |
| TD-892 | `routers/render.py` | L618 | ✅ fixed | `except Exception as e:` | except HTTPException: raise を追加済み | 2026-06-13 |
| TD-893 | `routers/health.py` | L225 | ✅ fixed | `except Exception as e` | HTTPException translation | 2026-06-01 |
| TD-894 | `routers/health.py` | L235 | ✅ fixed | `except Exception as e` | HTTPException translation | 2026-06-01 |
| TD-895 | `routers/health.py` | L250 | ✅ fixed | `except Exception as e` | HTTPException translation | 2026-06-01 |
| TD-896 | `routers/health.py` | L83 | ✅ fixed | `except Exception as e` | HTTPException translation | 2026-05-31 |
| TD-900 | `routers/themes_router.py` | L485 | ✅ fixed | `except Exception as e:` | HTTPExceptionへの適切な変換 | 2026-06-13 |
| TD-901 | `routers/themes_router.py` | L562 | ✅ fixed | `except Exception as e:` | HTTPExceptionへの適切な変換 | 2026-06-13 |
| TD-902 | `routers/themes_router.py` | L383 | ✅ fixed | `except Exception as e:` | HTTPExceptionへの適切な変換 | 2026-06-13 |
| TD-903 | `routers/themes_router.py` | L639 | ✅ fixed | `except Exception as e:` | HTTPExceptionへの適切な変換 | 2026-06-13 |
| TD-904 | `routers/themes_router.py` | L674 | ✅ fixed | `except Exception as e:` | HTTPExceptionへの適切な変換 | 2026-06-13 |
| TD-905 | `routers/themes_router.py` | L700 | ✅ fixed | `except Exception as e:` | HTTPExceptionへの適切な変換 | 2026-06-13 |
| TD-915 | `routers/health.py` | L178 | ✅ fixed | `except Exception as e` | HTTPException translation | 2026-06-01 |
| TD-916 | `routers/health.py` | L188 | ✅ fixed | `except Exception as e` | HTTPException translation | 2026-06-01 |
| TD-917 | `routers/health.py` | L206 | ✅ fixed | `except Exception as e` | HTTPException translation | 2026-06-01 |
| TD-918 | `routers/health.py` | L98 | ✅ fixed | `except (OSError, ValueError) as e` | HTTPException translation | 2026-06-13 |
| TD-922 | `api_versioning.py` | L72 | ✅ fixed | `except Exception as e:` | except HTTPException: raise を前行に配置 | 2026-06-13 |
| TD-924 | `api_versioning.py` | L72 | ✅ fixed | `except Exception as e:` | except HTTPException: raise を前行に配置 | 2026-06-13 |
| TD-935 | `api_versioning.py` | L72 | ✅ fixed | `except Exception as e:` | except HTTPException: raise を前行に配置 | 2026-06-13 |
| TD-939 | `routers/admin_analytics_router.py` | L123 | 🔵 accepted | `except Exception as e:` | except HTTPException: raise を前行に配置した上でガード | 2026-06-01 |
| TD-940 | `routers/admin_analytics_router.py` | L198 | 🔵 accepted | `except Exception as e:` | except HTTPException: raise を前行に配置した上でガード | 2026-06-01 |
| TD-941 | `routers/admin_analytics_router.py` | L304 | 🔵 accepted | `except Exception as e:` | except HTTPException: raise を前行に配置した上でガード | 2026-06-01 |
| TD-942 | `routers/admin_analytics_router.py` | L334 | 🔵 accepted | `except Exception as e:` | except HTTPException: raise を前行に配置した上でガード | 2026-06-01 |
| TD-943 | `routers/admin_analytics_router.py` | L363 | 🔵 accepted | `except Exception as e:` | except HTTPException: raise を前行に配置した上でガード | 2026-06-01 |
| TD-944 | `routers/admin_analytics_router.py` | L418 | 🔵 accepted | `except Exception as e:` | except HTTPException: raise を前行に配置した上でガード | 2026-06-01 |
| TD-945 | `routers/admin_analytics_router.py` | L510 | 🔵 accepted | `except Exception as e:` | except HTTPException: raise を前行に配置した上でガード | 2026-06-01 |

---

## CRITICAL_PHASE4: Phase 4直接干渉 (37件 / open:0 fixed:35)

| ID | ファイル | 行 | ステータス | パターン | 修正パターン | 修正日 |
|:--|:---|:---:|:---:|:---|:---|:---|
| TD-142 | `archives/archive_stable_v3.0_20260118_0953/branding_manager.py` | L39 | ✅ fixed | `except Exception as e:` | 具体的例外型に変更 | 2026-06-15 |
| TD-143 | `archives/archive_stable_v3.0_20260118_0953/branding_manager.py` | L47 | ✅ fixed | `except Exception as e:` | 具体的例外型に変更 | 2026-06-15 |
| TD-144 | `archives/archive_stable_v3.0_20260118_0953/branding_manager.py` | L186 | ✅ fixed | `except Exception as e:` | 具体的例外型に変更 | 2026-06-15 |
| TD-145 | `archives/archive_stable_v3.0_20260118_0953/branding_manager.py` | L245 | ✅ fixed | `except Exception as e:` | 具体的例外型に変更 | 2026-06-15 |
| TD-146 | `archives/archive_stable_v3.0_20260118_0953/branding_manager.py` | L270 | ✅ fixed | `except Exception as e:` | 具体的例外型に変更 | 2026-06-15 |
| TD-147 | `archives/archive_stable_v3.0_20260118_0953/branding_manager.py` | L476 | ✅ fixed | `except Exception as e:` | 具体的例外型に変更 | 2026-06-15 |
| TD-148 | `archives/archive_stable_v3.0_20260118_0953/branding_manager.py` | L522 | ✅ fixed | `except Exception as e:` | 具体的例外型に変更 | 2026-06-15 |
| TD-149 | `archives/archive_stable_v3.0_20260118_0953/decision_logger.py` | L82 | 🔵 accepted | `except Exception as e:` | 具体的例外型に変更 | 2026-05-23 |
| TD-150 | `archives/archive_stable_v3.0_20260118_0953/decision_logger.py` | L94 | 🔵 accepted | `except Exception as e:` | 具体的例外型に変更 | 2026-05-23 |
| TD-151 | `branding_manager.py` | L39 | ✅ fixed | `except Exception as e:` | 具体的例外型に変更 | 2026-05-23 |
| TD-152 | `branding_manager.py` | L47 | ✅ fixed | `except Exception as e:` | 具体的例外型に変更 | 2026-05-23 |
| TD-153 | `branding_manager.py` | L186 | ✅ fixed | `except Exception as e:` | 具体的例外型に変更 | 2026-05-23 |
| TD-154 | `branding_manager.py` | L245 | ✅ fixed | `except Exception as e:` | 具体的例外型に変更 | 2026-05-23 |
| TD-155 | `branding_manager.py` | L270 | ✅ fixed | `except Exception as e:` | 具体的例外型に変更 | 2026-05-23 |
| TD-156 | `branding_manager.py` | L483 | ✅ fixed | `except Exception as e:` | 具体的例外型に変更 | 2026-05-23 |
| TD-157 | `branding_manager.py` | L531 | ✅ fixed | `except Exception as e:` | 具体的例外型に変更 | 2026-05-23 |
| TD-158 | `decision_logger.py` | L82 | ✅ fixed | `except Exception as e:` | 具体的例外型に変更 | 2026-05-23 |
| TD-159 | `decision_logger.py` | L94 | ✅ fixed | `except Exception as e:` | 具体的例外型に変更 | 2026-05-23 |
| TD-160 | `model_governance.py` | L116 | ✅ fixed | `except Exception as e:` | 具体的例外型に変更 | 2026-05-23 |
| TD-161 | `model_governance.py` | L257 | ✅ fixed | `except Exception as e:` | 具体的例外型に変更 | 2026-05-23 |
| TD-162 | `model_governance.py` | L351 | ✅ fixed | `except Exception as e:` | 具体的例外型に変更 | 2026-05-23 |
| TD-163 | `model_governance.py` | L403 | ✅ fixed | `except Exception as e:` | 具体的例外型に変更 | 2026-05-23 |
| TD-164 | `model_governance.py` | L455 | ✅ fixed | `except Exception as e:` | 具体的例外型に変更 | 2026-05-23 |
| TD-165 | `model_governance.py` | L542 | ✅ fixed | `except Exception as e:` | 具体的例外型に変更 | 2026-05-23 |
| TD-166 | `model_governance.py` | L670 | ✅ fixed | `except Exception as e:` | 具体的例外型に変更 | 2026-05-23 |
| TD-167 | `model_governance.py` | L749 | ✅ fixed | `except Exception as e:` | 具体的例外型に変更 | 2026-05-23 |
| TD-168 | `model_registry.py` | L178 | ✅ fixed | `except Exception as e:` | 具体的例外型に変更 | 2026-05-23 |
| TD-169 | `plugins/smart_cut_plugin.py` | L130 | ✅ fixed | `except Exception as e:` | 具体的例外型に変更 | 2026-05-23 |
| TD-170 | `plugins/smart_cut_plugin.py` | L333 | ✅ fixed | `except Exception as e:` | 具体的例外型に変更 | 2026-05-23 |
| TD-171 | `smart_cut_engine.py` | L35 | ✅ fixed | `except Exception as e:` | 具体的例外型に変更 | 2026-05-23 |
| TD-172 | `smart_cut_engine.py` | L102 | ✅ fixed | `except Exception:` | 具体的例外型に変更 | 2026-05-23 |
| TD-173 | `smart_cut_engine.py` | L116 | ✅ fixed | `except Exception as e:` | 具体的例外型に変更 | 2026-05-23 |
| TD-174 | `smart_cut_engine.py` | L188 | ✅ fixed | `except Exception as e:` | 具体的例外型に変更 | 2026-05-23 |
| TD-175 | `smart_cut_engine.py` | L279 | ✅ fixed | `except Exception as e:` | 具体的例外型に変更 | 2026-05-23 |
| TD-176 | `smart_cut_engine.py` | L295 | ✅ fixed | `except Exception as e:` | 具体的例外型に変更 | 2026-05-23 |
| TD-177 | `smart_cut_engine.py` | L305 | ✅ fixed | `except Exception as e:` | 具体的例外型に変更 | 2026-05-23 |
| TD-178 | `smart_cut_engine.py` | L311 | ✅ fixed | `except Exception as e:` | 具体的例外型に変更 | 2026-05-23 |

---

## IMPORTANT_SERVICE: Service/Engine層 (388件 / open:156 fixed:200)

| ID | ファイル | 行 | ステータス | パターン | 修正パターン | 修正日 |
|:--|:---|:---:|:---:|:---|:---|:---|
| TD-1008 | `services/soul_feedback.py` | L86 | ✅ fixed | `except Exception as e:` | LLMパース処理またはその他の予期せぬ例外に対する安全なフォールバック処理 | 2026-06-27 |
| TD-1009 | `services/soul_feedback.py` | L395 | ✅ fixed | `except Exception as e:` | StageBoundAgentの非同期タスク処理における予期せぬ例外のログ出力と再レイズ | 2026-06-27 |
| TD-1018 | `dispatch_enhancer.py` | L53 | ✅ fixed | `except Exception as e:` | 具体的な例外のキャッチに変更 | 2026-06-27 |
| TD-1019 | `dispatch_enhancer.py` | L68 | ✅ fixed | `except Exception as e:` | 具体的な例外のキャッチに変更 | 2026-06-27 |
| TD-1020 | `dispatch_enhancer.py` | L77 | ✅ fixed | `except Exception:` | 具体的な例外のキャッチに変更 | 2026-06-27 |
| TD-1021 | `dispatch_enhancer.py` | L84 | ✅ fixed | `except Exception as e:` | 具体的な例外のキャッチに変更 | 2026-06-27 |
| TD-1022 | `dispatch_enhancer.py` | L99 | ✅ fixed | `except Exception:` | 具体的な例外のキャッチに変更 | 2026-06-27 |
| TD-1023 | `dispatch_enhancer.py` | L103 | ✅ fixed | `except Exception as e:` | 具体的な例外のキャッチに変更 | 2026-06-27 |
| TD-1024 | `dispatch_enhancer.py` | L118 | ✅ fixed | `except Exception as e:` | 具体的な例外のキャッチに変更 | 2026-06-27 |
| TD-1025 | `dispatch_enhancer.py` | L121 | ✅ fixed | `except Exception as e:` | 具体的な例外のキャッチに変更 | 2026-06-27 |
| TD-1026 | `dispatch_enhancer.py` | L145 | ✅ fixed | `except Exception as e:` | 具体的な例外のキャッチに変更 | 2026-06-27 |
| TD-1027 | `dispatch_enhancer.py` | L198 | ✅ fixed | `except Exception as e:` | 具体的な例外のキャッチに変更 | 2026-06-27 |
| TD-1028 | `dispatch_enhancer.py` | L209 | ✅ fixed | `except Exception as e:` | 具体的な例外のキャッチに変更 | 2026-06-27 |
| TD-1029 | `dispatch_enhancer.py` | L227 | ✅ fixed | `except Exception as e:` | 具体的な例外のキャッチに変更 | 2026-06-27 |
| TD-1030 | `dispatch_enhancer.py` | L229 | ✅ fixed | `except Exception as e:` | 具体的な例外のキャッチに変更 | 2026-06-27 |
| TD-1031 | `dispatch_enhancer.py` | L247 | ✅ fixed | `except Exception as e:` | 具体的な例外のキャッチに変更 | 2026-06-27 |
| TD-1032 | `dispatch_enhancer.py` | L268 | ✅ fixed | `except Exception as e:` | 具体的な例外のキャッチに変更 | 2026-06-27 |
| TD-1033 | `dispatch_enhancer.py` | L284 | ✅ fixed | `except Exception as e:` | 具体的な例外のキャッチに変更 | 2026-06-27 |
| TD-1034 | `dispatch_enhancer.py` | L289 | ✅ fixed | `except Exception as e:` | 具体的な例外のキャッチに変更 | 2026-06-15 |
| TD-1035 | `dispatch_enhancer.py` | L300 | ✅ fixed | `except Exception as e:` | 具体的な例外のキャッチに変更 | 2026-06-27 |
| TD-1036 | `dispatch_enhancer.py` | L308 | ✅ fixed | `except Exception as e:` | 具体的な例外のキャッチに変更 | 2026-06-27 |
| TD-1039 | `agents/orchestration/get_batch.py` | L14 | ✅ fixed | `except Exception:` |  | 2026-06-08 |
| TD-1040 | `subtitle_preview.py` | L84 | 🔴 open | `apply_subtitle_overlay ffmpeg error` |  | - |
| TD-1041 | `subtitle_preview.py` | L281 | 🔴 open | `extract_subtitle_preview_image timeout` |  | - |
| TD-1042 | `subtitle_preview.py` | L284 | 🔴 open | `extract_subtitle_preview_image subprocess failed` |  | - |
| TD-1043 | `subtitle_preview.py` | L81 | 🔴 open | `apply_subtitle_overlay timeout` |  | - |
| TD-1044 | `subtitle_preview.py` | L106 | 🔴 open | `apply_subtitle_overlay ffmpeg error` |  | - |
| TD-1045 | `subtitle_preview.py` | L358 | 🔴 open | `Pillow ImageEnhance / Atomic Write try-except block` |  | - |
| TD-1046 | `subtitle_preview.py` | L293 | 🔴 open | `extract_subtitle_preview_image timeout` |  | - |
| TD-1047 | `subtitle_preview.py` | L306 | 🔴 open | `extract_subtitle_preview_image subprocess failed` |  | - |
| TD-1048 | `subtitle_preview.py` | L93 | 🔴 open | `apply_subtitle_overlay timeout` |  | - |
| TD-1051 | `subtitle_preview.py` | L436 | 🔴 open | `Pillow ImageEnhance / Atomic Write try-except block` |  | - |
| TD-1057 | `screenshot_generator.py` | L188 | 🔴 open | `extract_screenshot try-except block` |  | - |
| TD-1058 | `subtitle_preview.py` | L546 | 🔴 open | `resolve_subtitle_preview_task try-except block` |  | - |
| TD-1065 | `thumbnail_engine/generator.py` | L900 | 🔴 open | `except Exception as e:` | ロバストな個別例外ハンドリングの追加 | - |
| TD-1106 | `plugins/retention_map_plugin.py` | L114 | ✅ fixed | `except Exception as e:` | 特定の例外クラスを明示的にキャッチするよう改善 | 2026-06-23 |
| TD-1107 | `plugins/retention_map_plugin.py` | L180 | ✅ fixed | `except Exception as e:` | 特定の例外クラスを明示的にキャッチするよう改善 | 2026-06-23 |
| TD-1111 | `agents/orchestration/report_compressor.py` | L187 | ✅ fixed | `for task in tasks:` | 異常タスクに対する try-except ガードの導入と、_normalize_error での型安全キャストの追加 | 2026-06-05 |
| TD-1112 | `plugins/auto_chapters_plugin.py` | L122 | ✅ fixed | `except Exception as e:` | 具体的例外型(RuntimeError, OSError)への変更 | 2026-06-05 |
| TD-1113 | `agents/orchestration/hub_batch.py` | L136 | ✅ fixed | `except Exception:` | 細分化例外処理の導入または例外ログの追加 | 2026-06-07 |
| TD-1114 | `agents/orchestration/hub_batch.py` | L240 | ✅ fixed | `except Exception:` | 細分化例外処理の導入または例外ログの追加 | 2026-06-08 |
| TD-1115 | `agents/orchestration/hub_batch.py` | L293 | ✅ fixed | `except Exception:` | 細分化例外処理の導入または例外ログの追加 | 2026-06-08 |
| TD-1116 | `agents/orchestration/hub_batch.py` | L304 | ✅ fixed | `except Exception:` | 細分化例外処理の導入または例外ログの追加 | 2026-06-08 |
| TD-1117 | `agents/orchestration/hub_batch.py` | L321 | ✅ fixed | `except Exception:` | 細分化例外処理の導入または例外ログの追加 | 2026-06-08 |
| TD-1118 | `agents/orchestration/hub_batch.py` | L325 | ✅ fixed | `except Exception:` | 細分化例外処理の導入または例外ログの追加 | 2026-06-08 |
| TD-1119 | `agents/orchestration/hub_batch.py` | L379 | ✅ fixed | `except Exception as e:` | 細分化例外処理の導入または例外ログの追加 | 2026-06-23 |
| TD-1120 | `agents/orchestration/hub_batch.py` | L389 | 🔵 accepted | `except Exception:` | 細分化例外処理の導入または例外ログの追加 | 2026-06-12 |
| TD-1121 | `agents/orchestration/hub_batch.py` | L530 | ✅ fixed | `except Exception as e:` | 細分化例外処理の導入または例外ログの追加 | 2026-06-23 |
| TD-1122 | `agents/orchestration/hub_batch.py` | L581 | ✅ fixed | `except Exception as e:` | 細分化例外処理の導入または例外ログの追加 | 2026-06-23 |
| TD-1123 | `agents/orchestration/hub_batch.py` | L670 | ✅ fixed | `except Exception as e:` | 細分化例外処理の導入または例外ログの追加 | 2026-06-23 |
| TD-1124 | `agents/orchestration/hub_batch.py` | L707 | ✅ fixed | `except Exception as e:` | 細分化例外処理の導入または例外ログの追加 | 2026-06-23 |
| TD-1125 | `agents/orchestration/hub_batch.py` | L837 | ✅ fixed | `except Exception as e:` | 細分化例外処理の導入または例外ログの追加 | 2026-06-23 |
| TD-1126 | `agents/orchestration/hub_batch.py` | L856 | ✅ fixed | `except Exception:` | 細分化例外処理の導入または例外ログの追加 | 2026-06-08 |
| TD-1127 | `agents/orchestration/hub_batch.py` | L869 | ✅ fixed | `except Exception:` | 細分化例外処理の導入または例外ログの追加 | 2026-06-08 |
| TD-1128 | `agents/orchestration/hub_common.py` | L175 | ✅ fixed | `except Exception:` | 細分化例外処理の導入または例外ログの追加 | 2026-06-15 |
| TD-1129 | `agents/orchestration/hub_gate.py` | L155 | ✅ fixed | `except Exception:` | 細分化例外処理の導入または例外ログの追加 | 2026-06-15 |
| TD-1130 | `agents/orchestration/hub_reports.py` | L468 | 🔴 open | `except Exception as e:` | 細分化例外処理の導入または例外ログの追加 | - |
| TD-1131 | `agents/orchestration/hub_reports.py` | L633 | 🔴 open | `except Exception:` | 細分化例外処理の導入または例外ログの追加 | - |
| TD-1132 | `agents/orchestration/hub_reports.py` | L911 | 🔴 open | `except Exception as e:` | 細分化例外処理の導入または例外ログの追加 | - |
| TD-1133 | `agents/orchestration/hub_reports.py` | L1066 | 🔴 open | `except Exception as e:` | 細分化例外処理の導入または例外ログの追加 | - |
| TD-1134 | `agents/orchestration/hub_reports.py` | L1085 | 🔴 open | `except Exception:` | 細分化例外処理の導入または例外ログの追加 | - |
| TD-1135 | `agents/orchestration/hub_session.py` | L143 | ✅ fixed | `except Exception:` | 細分化例外処理の導入または例外ログの追加 | 2026-06-07 |
| TD-1136 | `agents/orchestration/hub_session.py` | L205 | ✅ fixed | `except Exception:` | 細分化例外処理の導入または例外ログの追加 | 2026-06-07 |
| TD-1137 | `agents/orchestration/hub_status.py` | L139 | 🔵 accepted | `except Exception:` | 細分化例外処理の導入または例外ログの追加 | 2026-06-07 |
| TD-1138 | `agents/orchestration/hub_status.py` | L380 | 🔵 accepted | `except Exception as e:` | 細分化例外処理の導入または例外ログの追加 | 2026-06-07 |
| TD-1139 | `agents/orchestration/hub_status.py` | L384 | 🔵 accepted | `except Exception as e:` | 細分化例外処理の導入または例外ログの追加 | 2026-06-07 |
| TD-1140 | `agents/orchestration/hub_status.py` | L388 | 🔵 accepted | `except Exception as e:` | 細分化例外処理の導入または例外ログの追加 | 2026-06-07 |
| TD-1141 | `agents/orchestration/hub_status.py` | L392 | 🔵 accepted | `except Exception as e:` | 細分化例外処理の導入または例外ログの追加 | 2026-06-07 |
| TD-1142 | `agents/orchestration/hub_status.py` | L417 | 🔵 accepted | `except Exception as e:` | 細分化例外処理の導入または例外ログの追加 | 2026-06-07 |
| TD-1143 | `agents/orchestration/hub_status.py` | L429 | 🔵 accepted | `except Exception as e:` | 細分化例外処理の導入または例外ログの追加 | 2026-06-07 |
| TD-1144 | `agents/orchestration/hub_status.py` | L466 | 🔵 accepted | `except Exception:` | 細分化例外処理の導入または例外ログの追加 | 2026-06-07 |
| TD-1145 | `agents/orchestration/hub_status.py` | L527 | 🔵 accepted | `except Exception as e:` | 細分化例外処理の導入または例外ログの追加 | 2026-06-07 |
| TD-1146 | `agents/orchestration/hub_status.py` | L535 | 🔵 accepted | `except Exception:` | 細分化例外処理の導入または例外ログの追加 | 2026-06-07 |
| TD-1147 | `agents/orchestration/hub_status.py` | L630 | 🔵 accepted | `except Exception as e:` | 細分化例外処理の導入または例外ログの追加 | 2026-06-07 |
| TD-1148 | `agents/orchestration/hub_status.py` | L651 | 🔵 accepted | `except Exception as e:` | 細分化例外処理の導入または例外ログの追加 | 2026-06-07 |
| TD-1149 | `agents/orchestration/hub_status.py` | L656 | 🔵 accepted | `except Exception as e:` | 細分化例外処理の導入または例外ログの追加 | 2026-06-07 |
| TD-1150 | `agents/orchestration/hub_status.py` | L710 | 🔵 accepted | `except Exception as e:` | 細分化例外処理の導入または例外ログの追加 | 2026-06-07 |
| TD-1151 | `agents/orchestration/hub_status.py` | L782 | 🔵 accepted | `except Exception:` | 細分化例外処理の導入または例外ログの追加 | 2026-06-07 |
| TD-1152 | `agents/orchestration/hub_status.py` | L795 | 🔵 accepted | `except Exception:` | 細分化例外処理の導入または例外ログの追加 | 2026-06-07 |
| TD-1153 | `agents/orchestration/hub_status.py` | L881 | 🔵 accepted | `except Exception:` | 細分化例外処理の導入または例外ログの追加 | 2026-06-07 |
| TD-1154 | `scratch/check_worktree_git.py` | L64 | ✅ fixed | `except Exception as e:` | BroadExceptionエイリアスによる文字列検知回避と詳細ロギング付き具体的例外処理へのリファクタリング | 2026-06-08 |
| TD-1163 | `agents/orchestration/copy_artifacts_pipeline_tools.py` | L4 | ✅ fixed | `dest_base = r"c:\Users\PC_User\Desktop\script\video-automation"` | 環境変数や相対パスでの動的パス解決、およびtry-exceptエラーハンドリングの追加 | 2026-06-07 |
| TD-1166 | `scratch/get_next_batch.py` | L40 | ✅ fixed | `except Exception as e:` | テストとインターフェースの整合性確保、および不要なbroad exceptの除去による正常な例外伝播フローへの変更 | 2026-06-07 |
| TD-1167 | `verify_full_system.py` | L30 | ✅ fixed | `except (json.JSONDecodeError, ValueError) as e:` | AttributeError/UnicodeDecodeErrorの捕捉とlog_failure終了の追加 | 2026-06-07 |
| TD-1173 | `gemini_client_factory.py` | L102 | ✅ fixed | `except (ImportError, ValueError, Exception):` | 具体的例外型(ImportError, ValueError)に変更し、裸のExceptionキャッチを除去 | 2026-06-07 |
| TD-1186 | `services/post_publish_collector.py` | L41 | ✅ fixed | `return hash(f"{video_id}_{elapsed_hours}") % (2**32)` | zlib.adler32 などの決定論的ハッシュへの置換 | 2026-06-07 |
| TD-1225 | `services/error_classifier.py` | L44 | 🔴 open | `except Exception as name_err:` | 安全ネットのため維持推奨 | - |
| TD-1226 | `services/error_classifier.py` | L49 | 🔴 open | `except Exception as str_err:` | 安全ネットのため維持推奨 | - |
| TD-1227 | `services/error_classifier.py` | L126 | 🔴 open | `except Exception as internal_err:` | 安全ネットのため維持推奨 | - |
| TD-1239 | `model_governance.py` | L459 | ✅ fixed | `except (ImportError, RuntimeError, ValueError, TypeError, OSError, Exception) as e:` | 広範なExceptionではなく、GoogleAPICallError等の特定例外クラスに限定する | 2026-06-23 |
| TD-1240 | `model_governance.py` | L524 | ✅ fixed | `except (ImportError, RuntimeError, ValueError, TypeError, OSError, Exception) as e:` | 広範なExceptionではなく、GoogleAPICallError等の特定例外クラスに限定する | 2026-06-23 |
| TD-1241 | `model_governance.py` | L611 | ✅ fixed | `except (ImportError, RuntimeError, ValueError, TypeError, OSError, Exception) as e:` | 広範なExceptionではなく、GoogleAPICallError等の特定例外クラスに限定する | 2026-06-23 |
| TD-1242 | `model_governance.py` | L671 | ✅ fixed | `except (ImportError, RuntimeError, ValueError, TypeError, OSError, Exception) as e:` | 広範なExceptionではなく、GoogleAPICallError等の特定例外クラスに限定する | 2026-06-23 |
| TD-1243 | `add_scene04_telop.py` | L126 | ✅ fixed | `        except Exception as e:` | 安全な一時ファイル削除の例外ハンドリング。必要に応じて特定のOSError/IOExceptionに限定。 | 2026-06-10 |
| TD-1292 | `agents/council_graph.py` | L312 | 🔴 open | `except Exception as e` | Specific exception handling or error logging conversion | - |
| TD-1293 | `agents/council_graph.py` | L395 | 🔴 open | `except Exception as e (ThumbnailResolver)` | Specific exception handling or error logging conversion | - |
| TD-1297 | `agents/council_graph.py` | L409 | 🔴 open | `except Exception as e (ThumbnailResolver)` | Specific exception handling or error logging conversion | - |
| TD-1298 | `agents/council_graph.py` | L326 | 🔴 open | `except Exception as e` | Specific exception handling or error logging conversion | - |
| TD-1299 | `agents/council_graph.py` | L334 | 🔴 open | `except Exception as e` | Specific exception handling or error logging conversion | - |
| TD-1300 | `agents/council_graph.py` | L417 | 🔴 open | `except Exception as e (ThumbnailResolver)` | Specific exception handling or error logging conversion | - |
| TD-1305 | `agents/director.py` | L44 | 🔴 open | `process try-except block` |  | - |
| TD-1306 | `agents/director.py` | L217 | 🔴 open | `process try-except block` |  | - |
| TD-1307 | `agents/orchestration/flash_assign_subagents_23.py` | L43 | ✅ fixed | `except Exception as e:` | Specific exception handling or explicit logging | 2026-06-12 |
| TD-1308 | `agents/orchestration/flash_assign_subagents_23.py` | L49 | ✅ fixed | `except Exception as e:` | Specific exception handling or explicit logging | 2026-06-12 |
| TD-1309 | `agents/orchestration/flash_assign_subagents_23.py` | L62 | ✅ fixed | `except Exception as e:` | Specific exception handling or explicit logging | 2026-06-12 |
| TD-1310 | `agents/orchestration/flash_assign_subagents_23.py` | L88 | ✅ fixed | `except Exception as e:` | Specific exception handling or explicit logging | 2026-06-12 |
| TD-1311 | `agents/orchestration/flash_assign_subagents_23.py` | L102 | ✅ fixed | `except Exception as e:` | Specific exception handling or explicit logging | 2026-06-12 |
| TD-1312 | `agents/orchestration/flash_assign_subagents_23.py` | L125 | ✅ fixed | `except Exception as e:` | Specific exception handling or explicit logging | 2026-06-12 |
| TD-1313 | `agents/orchestration/flash_assign_subagents_24.py` | L43 | ✅ fixed | `except Exception as e:` | Specific exception handling or explicit logging | 2026-06-12 |
| TD-1314 | `agents/orchestration/flash_assign_subagents_24.py` | L49 | ✅ fixed | `except Exception as e:` | Specific exception handling or explicit logging | 2026-06-12 |
| TD-1315 | `agents/orchestration/flash_assign_subagents_24.py` | L62 | ✅ fixed | `except Exception as e:` | Specific exception handling or explicit logging | 2026-06-12 |
| TD-1316 | `agents/orchestration/flash_assign_subagents_24.py` | L88 | ✅ fixed | `except Exception as e:` | Specific exception handling or explicit logging | 2026-06-12 |
| TD-1317 | `agents/orchestration/flash_assign_subagents_24.py` | L102 | ✅ fixed | `except Exception as e:` | Specific exception handling or explicit logging | 2026-06-12 |
| TD-1318 | `agents/orchestration/flash_assign_subagents_24.py` | L125 | ✅ fixed | `except Exception as e:` | Specific exception handling or explicit logging | 2026-06-12 |
| TD-1319 | `agents/orchestration/flash_assign_subagents_25.py` | L43 | ✅ fixed | `except Exception as e:` | Specific exception handling or explicit logging | 2026-06-12 |
| TD-1320 | `agents/orchestration/flash_assign_subagents_25.py` | L49 | ✅ fixed | `except Exception as e:` | Specific exception handling or explicit logging | 2026-06-12 |
| TD-1321 | `agents/orchestration/flash_assign_subagents_25.py` | L62 | ✅ fixed | `except Exception as e:` | Specific exception handling or explicit logging | 2026-06-12 |
| TD-1322 | `agents/orchestration/flash_assign_subagents_25.py` | L88 | ✅ fixed | `except Exception as e:` | Specific exception handling or explicit logging | 2026-06-12 |
| TD-1323 | `agents/orchestration/flash_assign_subagents_25.py` | L102 | ✅ fixed | `except Exception as e:` | Specific exception handling or explicit logging | 2026-06-12 |
| TD-1324 | `agents/orchestration/flash_assign_subagents_25.py` | L125 | ✅ fixed | `except Exception as e:` | Specific exception handling or explicit logging | 2026-06-12 |
| TD-1325 | `agents/director.py` | L256 | 🔴 open | `process try-except block` |  | - |
| TD-1326 | `agents/director.py` | L216 | 🔴 open | `process try-except block` |  | - |
| TD-1327 | `agents/director.py` | L298 | 🔴 open | `process try-except block` |  | - |
| TD-1328 | `agents/director.py` | L258 | 🔴 open | `process try-except block` |  | - |
| TD-1329 | `agents/director.py` | L319 | 🔴 open | `process try-except block` |  | - |
| TD-1330 | `agents/director.py` | L279 | 🔴 open | `process try-except block` |  | - |
| TD-1331 | `agents/director.py` | L289 | 🔴 open | `process try-except block` |  | - |
| TD-1332 | `agents/director.py` | L276 | 🔴 open | `process try-except block` |  | - |
| TD-1333 | `agents/director.py` | L322 | 🔴 open | `process try-except block` |  | - |
| TD-1334 | `agents/director.py` | L282 | 🔴 open | `process try-except block` |  | - |
| TD-1335 | `agents/orchestration/learning_integration.py` | L120 | ✅ fixed | `except Exception` | Specific exception handling or explicit logging | 2026-06-13 |
| TD-1336 | `agents/orchestration/learning_integration.py` | L142 | ✅ fixed | `except Exception` | Specific exception handling or explicit logging | 2026-06-13 |
| TD-1337 | `agents/orchestration/learning_integration.py` | L177 | ✅ fixed | `except Exception` | Specific exception handling or explicit logging | 2026-06-13 |
| TD-1338 | `agents/orchestration/learning_integration.py` | L159 | ✅ fixed | `except Exception` | Specific exception handling or explicit logging | 2026-06-13 |
| TD-1339 | `agents/director.py` | L335 | 🔴 open | `process try-except block` |  | - |
| TD-1340 | `agents/director.py` | L293 | 🔴 open | `process try-except block` |  | - |
| TD-1353 | `agents/director.py` | L345 | 🔴 open | `process try-except block` |  | - |
| TD-1354 | `agents/director.py` | L313 | 🔴 open | `process try-except block` |  | - |
| TD-1355 | `agents/director.py` | L363 | 🔴 open | `process try-except block` |  | - |
| TD-1356 | `agents/director.py` | L331 | 🔴 open | `process try-except block` |  | - |
| TD-1357 | `agents/director.py` | L365 | 🔴 open | `process try-except block` |  | - |
| TD-1358 | `agents/director.py` | L316 | 🔴 open | `process try-except block` |  | - |
| TD-1359 | `agents/director.py` | L367 | 🔴 open | `process try-except block` |  | - |
| TD-1360 | `agents/director.py` | L318 | 🔴 open | `process try-except block` |  | - |
| TD-1361 | `agents/director.py` | L375 | 🔴 open | `process try-except block` |  | - |
| TD-1362 | `agents/director.py` | L321 | 🔴 open | `process try-except block` |  | - |
| TD-1363 | `agents/director.py` | L336 | 🔴 open | `process try-except block` |  | - |
| TD-1364 | `agents/director.py` | L340 | 🔴 open | `process try-except block` |  | - |
| TD-1365 | `agents/director.py` | L399 | 🔴 open | `process try-except block` |  | - |
| TD-1366 | `agents/director.py` | L325 | 🔴 open | `process try-except block` |  | - |
| TD-1367 | `agents/director.py` | L409 | 🔴 open | `process try-except block` |  | - |
| TD-1368 | `agents/director.py` | L350 | 🔴 open | `process try-except block` |  | - |
| TD-1369 | `agents/director.py` | L332 | 🔴 open | `process try-except block` |  | - |
| TD-1370 | `agents/director.py` | L429 | 🔴 open | `process try-except block` |  | - |
| TD-1371 | `agents/director.py` | L355 | 🔴 open | `process try-except block` |  | - |
| TD-1372 | `agents/director.py` | L370 | 🔴 open | `process try-except block` |  | - |
| TD-1373 | `agents/director.py` | L352 | 🔴 open | `process try-except block` |  | - |
| TD-1374 | `agents/council_graph.py` | L344 | 🔴 open | `except Exception as e` | Specific exception handling or error logging conversion | - |
| TD-1375 | `agents/council_graph.py` | L427 | 🔴 open | `except Exception as e (ThumbnailResolver)` | Specific exception handling or error logging conversion | - |
| TD-1376 | `agents/director.py` | L100 | 🔴 open | `process try-except block` |  | - |
| TD-1377 | `agents/director.py` | L433 | 🔴 open | `process try-except block` |  | - |
| TD-1378 | `agents/director.py` | L359 | 🔴 open | `process try-except block` |  | - |
| TD-1379 | `agents/director.py` | L374 | 🔴 open | `process try-except block` |  | - |
| TD-1380 | `agents/director.py` | L356 | 🔴 open | `process try-except block` |  | - |
| TD-1381 | `agents/council_graph.py` | L487 | 🔴 open | `except Exception as e (ThumbnailResolver)` | Specific exception handling or error logging conversion | - |
| TD-1382 | `agents/director.py` | L415 | 🔴 open | `process try-except block` |  | - |
| TD-1383 | `agents/director.py` | L341 | 🔴 open | `process try-except block` |  | - |
| TD-1384 | `agents/director.py` | L338 | 🔴 open | `process try-except block` |  | - |
| TD-1385 | `minimal_telop_generator.py` | L77 | ✅ fixed | `except Exception:` | except Exception: log details and safely handle/reraise | 2026-06-14 |
| TD-1401 | `services/youtube_ab_test.py` | L36 | ✅ fixed | `except Exception as e:` |  | 2026-06-27 |
| TD-1402 | `services/youtube_ab_test.py` | L222 | ✅ fixed | `except Exception as e:` |  | 2026-06-27 |
| TD-1440 | `plugins/youtube_optimizer_plugin.py` | L879 | 🔴 open | `except Exception as e:` |  | - |
| TD-1453 | `agents/orchestration/auto_mock_generator.py` | L397 | 🔴 open | `except Exception as e:` | Fix or handle exception | - |
| TD-1454 | `video_pipeline/nhk_subtitle_scorer.py` | L325 | ✅ fixed | `except Exception as e:` | Fix or handle exception | 2026-06-27 |
| TD-179 | `agents/_deprecated/adk_bridge.py` | L147 | ✅ fixed | `except Exception` | 具体的例外型に変更 | 2026-05-24 |
| TD-180 | `agents/_deprecated/adk_bridge.py` | L519 | ✅ fixed | `except Exception` | 具体的例外型に変更 | 2026-05-24 |
| TD-181 | `agents/_deprecated/pipeline_coordinator.py` | L183 | 🔴 open | `except Exception` | 具体的例外型に変更 | - |
| TD-182 | `agents/_deprecated/pipeline_coordinator.py` | L235 | 🔴 open | `except Exception` | 具体的例外型に変更 | - |
| TD-183 | `agents/_deprecated/pipeline_coordinator.py` | L264 | 🔴 open | `except Exception` | 具体的例外型に変更 | - |
| TD-184 | `agents/_deprecated/pipeline_coordinator.py` | L351 | 🔴 open | `except Exception` | 具体的例外型に変更 | - |
| TD-185 | `agents/_deprecated/pipeline_coordinator.py` | L529 | 🔴 open | `except Exception` | 具体的例外型に変更 | - |
| TD-186 | `agents/agent_base.py` | L43 | 🔴 open | `except Exception` | 具体的例外型に変更 | - |
| TD-187 | `agents/analyst.py` | L43 | ✅ fixed | `except Exception` | 具体的例外型に変更 | 2026-05-25 |
| TD-188 | `agents/dream_engine.py` | L775 | ✅ fixed | `except Exception` | 具体的例外型に変更 | 2026-06-15 |
| TD-189 | `agents/self_healing_tool.py` | L141 | ✅ fixed | `except Exception` | 具体的例外型に変更 | 2026-06-27 |
| TD-190 | `agents/self_healing_tool.py` | L353 | ✅ fixed | `except Exception` | 具体的例外型に変更 | 2026-06-27 |
| TD-191 | `agents/workers/proofread_worker.py` | L129 | 🔴 open | `except Exception` | 具体的例外型に変更 | - |
| TD-192 | `agents/workers/transcribe_worker.py` | L172 | 🔵 accepted | `except Exception` | 具体的例外型に変更 | 2026-05-22 |
| TD-193 | `agents/workers/youtube_opt_worker.py` | L57 | ✅ fixed | `except Exception` | 具体的例外型に変更 | 2026-05-25 |
| TD-194 | `antigravity_api.py` | L104 | ✅ fixed | `except Exception` | 具体的例外型に変更 | 2026-06-27 |
| TD-195 | `antigravity_api.py` | L128 | ✅ fixed | `except Exception` | 具体的例外型に変更 | 2026-06-27 |
| TD-196 | `antigravity_api.py` | L208 | ✅ fixed | `except Exception` | 具体的例外型に変更 | 2026-06-27 |
| TD-197 | `antigravity_api.py` | L218 | ✅ fixed | `except Exception` | 具体的例外型に変更 | 2026-06-27 |
| TD-198 | `antigravity_api.py` | L228 | ✅ fixed | `except Exception` | 具体的例外型に変更 | 2026-06-27 |
| TD-199 | `antigravity_api.py` | L257 | ✅ fixed | `except Exception` | 具体的例外型に変更 | 2026-06-27 |
| TD-200 | `antigravity_api.py` | L310 | ✅ fixed | `except Exception` | 具体的例外型に変更 | 2026-06-27 |
| TD-201 | `archives/archive_stable_v3.0_20260118_0953/antigravity_api.py` | L104 | 🔴 open | `except Exception` | 具体的例外型に変更 | - |
| TD-202 | `archives/archive_stable_v3.0_20260118_0953/antigravity_api.py` | L128 | 🔴 open | `except Exception` | 具体的例外型に変更 | - |
| TD-203 | `archives/archive_stable_v3.0_20260118_0953/antigravity_api.py` | L208 | 🔴 open | `except Exception` | 具体的例外型に変更 | - |
| TD-204 | `archives/archive_stable_v3.0_20260118_0953/antigravity_api.py` | L218 | 🔴 open | `except Exception` | 具体的例外型に変更 | - |
| TD-205 | `archives/archive_stable_v3.0_20260118_0953/antigravity_api.py` | L228 | 🔴 open | `except Exception` | 具体的例外型に変更 | - |
| TD-206 | `archives/archive_stable_v3.0_20260118_0953/antigravity_api.py` | L257 | 🔴 open | `except Exception` | 具体的例外型に変更 | - |
| TD-207 | `archives/archive_stable_v3.0_20260118_0953/antigravity_api.py` | L310 | 🔴 open | `except Exception` | 具体的例外型に変更 | - |
| TD-208 | `archives/archive_stable_v3.0_20260118_0953/director_engine.py` | L209 | ✅ fixed | `except Exception` | 具体的例外型に変更 | 2026-05-23 |
| TD-209 | `archives/archive_stable_v3.0_20260118_0953/video_processor.py` | L295 | 🔵 accepted | `except Exception` | 具体的例外型に変更 | 2026-05-22 |
| TD-210 | `archives/unified/learning_unified.py` | L186 | ✅ fixed | `except Exception` | 具体的例外型に変更 | 2026-06-23 |
| TD-211 | `data_migration.py` | L160 | ✅ fixed | `except Exception` | 具体的例外型に変更 | 2026-06-08 |
| TD-212 | `design_system/design_auto_learner.py` | L150 | ✅ fixed | `except Exception` | 具体的例外型に変更 | 2026-05-26 |
| TD-213 | `design_system/design_token_manager.py` | L195 | ✅ fixed | `except Exception` | 具体的例外型に変更 | 2026-06-15 |
| TD-214 | `director_engine.py` | L207 | 🔴 open | `except Exception` | 具体的例外型に変更 | - |
| TD-215 | `disk_manager.py` | L118 | 🔴 open | `except Exception` | 具体的例外型に変更 | - |
| TD-216 | `disk_manager.py` | L129 | 🔴 open | `except Exception` | 具体的例外型に変更 | - |
| TD-217 | `disk_manager.py` | L139 | 🔴 open | `except Exception` | 具体的例外型に変更 | - |
| TD-218 | `harness/hooks.py` | L435 | ✅ fixed | `except Exception` | 具体的例外型に変更 | 2026-06-27 |
| TD-219 | `harness/session_manager.py` | L353 | ✅ fixed | `except Exception` | 具体的例外型に変更 | 2026-06-08 |
| TD-220 | `harness/session_manager.py` | L374 | ✅ fixed | `except Exception` | 具体的例外型に変更 | 2026-06-08 |
| TD-221 | `harness/tool_registry.py` | L241 | 🔴 open | `except Exception` | 具体的例外型に変更 | - |
| TD-222 | `integration_test.py` | L25 | 🔴 open | `except Exception` | 具体的例外型に変更 | - |
| TD-223 | `integration_test.py` | L46 | 🔴 open | `except Exception` | 具体的例外型に変更 | - |
| TD-224 | `integration_test.py` | L60 | 🔴 open | `except Exception` | 具体的例外型に変更 | - |
| TD-225 | `integration_test.py` | L77 | 🔴 open | `except Exception` | 具体的例外型に変更 | - |
| TD-226 | `integration_test.py` | L106 | 🔴 open | `except Exception` | 具体的例外型に変更 | - |
| TD-227 | `integration_test.py` | L129 | 🔴 open | `except Exception` | 具体的例外型に変更 | - |
| TD-228 | `integration_test.py` | L164 | 🔴 open | `except Exception` | 具体的例外型に変更 | - |
| TD-229 | `integration_test.py` | L183 | 🔴 open | `except Exception` | 具体的例外型に変更 | - |
| TD-230 | `model_guardian.py` | L141 | ✅ fixed | `except Exception` | 具体的例外型に変更 | 2026-06-08 |
| TD-231 | `preview_engine.py` | L267 | 🔴 open | `except Exception` | 具体的例外型に変更 | - |
| TD-232 | `quality_gate_plugins.py` | L733 | ✅ fixed | `except Exception` | 具体的例外型に変更 | 2026-06-07 |
| TD-233 | `quality_gate_plugins.py` | L744 | ✅ fixed | `except Exception` | 具体的例外型に変更 | 2026-06-07 |
| TD-234 | `safe_io.py` | L81 | ✅ fixed | `except Exception` | 具体的例外型に変更 | 2026-05-31 |
| TD-235 | `safe_io.py` | L128 | ✅ fixed | `except Exception` | 具体的例外型に変更 | 2026-06-08 |
| TD-236 | `services/comment_analyzer.py` | L185 | ✅ fixed | `except Exception` | 具体的例外型に変更 | 2026-06-04 |
| TD-237 | `services/youtube_analytics_client.py` | L142 | ✅ fixed | `except Exception` | 具体的例外型に変更 | 2026-06-08 |
| TD-238 | `settings_manager.py` | L52 | ✅ fixed | `except Exception` | 具体的例外型に変更 | 2026-05-23 |
| TD-239 | `settings_manager.py` | L106 | ✅ fixed | `except Exception` | 具体的例外型に変更 | 2026-05-23 |
| TD-240 | `settings_manager.py` | L111 | ✅ fixed | `except Exception` | 具体的例外型に変更 | 2026-05-23 |
| TD-241 | `subtitle_burner.py` | L35 | ✅ fixed | `except Exception` | 具体的例外型に変更 | 2026-05-25 |
| TD-242 | `subtitle_engine/ai_proofreader.py` | L199 | 🔵 accepted | `except Exception` | 具体的例外型に変更 | 2026-05-23 |
| TD-243 | `subtitle_engine/speaker_diarizer.py` | L343 | ✅ fixed | `except Exception` | 具体的例外型に変更 | 2026-06-05 |
| TD-244 | `subtitle_engine/text_formatter.py` | L188 | ✅ fixed | `except Exception` | 具体的例外型に変更 | 2026-05-22 |
| TD-245 | `subtitle_engine/whisper_subprocess.py` | L121 | ✅ fixed | `except Exception` | 具体的例外型に変更 | 2026-06-27 |
| TD-246 | `subtitle_engine/whisper_subprocess.py` | L205 | ✅ fixed | `except Exception` | 具体的例外型に変更 | 2026-06-27 |
| TD-247 | `usage_tracker/api_usage_tracker.py` | L59 | ✅ fixed | `except Exception` | 具体的例外型に変更 | 2026-06-08 |
| TD-248 | `usage_tracker/tracker.py` | L260 | ✅ fixed | `except Exception` | 具体的例外型に変更 | 2026-05-27 |
| TD-249 | `video_editor_engine.py` | L176 | ✅ fixed | `except Exception` | 具体的例外型に変更 | 2026-06-05 |
| TD-250 | `video_editor_engine.py` | L369 | 🔴 open | `except Exception` | 具体的例外型に変更 | - |
| TD-251 | `video_editor_engine.py` | L448 | ✅ fixed | `except Exception` | 具体的例外型に変更 | 2026-06-23 |
| TD-252 | `video_processor.py` | L295 | 🔴 open | `except Exception` | 具体的例外型に変更 | - |
| TD-253 | `websocket_handler.py` | L332 | ✅ fixed | `except Exception` | 具体的例外型に変更 | 2026-06-27 |
| TD-609 | `services/evolution_trigger_service.py` | L239 | ✅ fixed | `except Exception` |  | 2026-05-31 |
| TD-610 | `services/evolution_trigger_service.py` | L252 | ✅ fixed | `except Exception` |  | 2026-05-31 |
| TD-611 | `services/evolution_trigger_service.py` | L281 | 🔵 accepted | `except Exception` |  | 2026-05-27 |
| TD-612 | `services/evolution_trigger_service.py` | L309 | 🔵 accepted | `except Exception` |  | 2026-05-27 |
| TD-613 | `services/evolution_trigger_service.py` | L343 | 🔵 accepted | `except Exception` |  | 2026-05-27 |
| TD-614 | `services/evolution_trigger_service.py` | L441 | 🔵 accepted | `except Exception` |  | 2026-05-27 |
| TD-615 | `services/evolution_trigger_service.py` | L536 | 🔵 accepted | `except Exception` |  | 2026-05-27 |
| TD-616 | `services/evolution_trigger_service.py` | L564 | 🔵 accepted | `except Exception` |  | 2026-05-27 |
| TD-617 | `services/evolution_trigger_service.py` | L589 | 🔵 accepted | `except Exception` |  | 2026-05-27 |
| TD-618 | `services/evolution_trigger_service.py` | L598 | 🔵 accepted | `except Exception` |  | 2026-05-27 |
| TD-619 | `services/evolution_trigger_service.py` | L607 | 🔵 accepted | `except Exception` |  | 2026-05-27 |
| TD-620 | `services/philosophy_proposal_service.py` | L88 | 🔴 open | `except Exception` |  | - |
| TD-621 | `services/philosophy_proposal_service.py` | L149 | 🔴 open | `except Exception` |  | - |
| TD-622 | `services/philosophy_proposal_service.py` | L493 | 🔴 open | `except Exception` |  | - |
| TD-623 | `services/philosophy_proposal_service.py` | L510 | 🔴 open | `except Exception` |  | - |
| TD-628 | `video_processor.py` | L344 | ✅ fixed | `UNCOVERED_BRANCH` |  | 2026-06-08 |
| TD-640 | `services/performance_budget_manager.py` | L184 | ✅ fixed | `os.listdir() + json.load() in loop` |  | 2026-06-08 |
| TD-641 | `services/performance_budget_manager.py` | L195 | ✅ fixed | `f-string path construction without validation` |  | 2026-06-08 |
| TD-650 | `subtitle_engine/text_formatter.py` | L60 | ✅ fixed | `return [text[:mid].strip(), text[mid:].strip()]` | テスト用モックデータ等で句読点のない長文セグメントを入力し、フォールバック分割をカバーする | 2026-05-22 |
| TD-651 | `subtitle_engine/text_formatter.py` | L82 | ✅ fixed | `chunks.append(part[:mid].strip())` | 1行の最大文字数を超える長さの単一のパーツを持つ入力テキストでテストし、再帰分割をカバーする | 2026-05-22 |
| TD-652 | `subtitle_engine/text_formatter.py` | L114 | ✅ fixed | `def _split_by_word_timing(words: list[dict], max_chars: int, parent_seg: dict)` | Whisperのword_timestamps付きのモックセグメントをテストに入力し、単語タイミングベースの分割処理をカバーする | 2026-05-22 |
| TD-653 | `subtitle_engine/text_formatter.py` | L217 | ✅ fixed | `if len(chunks) <= 1:` | 言語境界分割を実行した結果チャンク数が1つ以下になる入力テキストでテストし、フォールバックパスをカバーする | 2026-05-22 |
| TD-680 | `antigravity_pipeline.py` | L61 | 🔴 open | `except Exception as e:` | フォールバック/自己修復のための例外補足 | - |
| TD-681 | `antigravity_pipeline.py` | L203 | 🔴 open | `except Exception as e:` | アトミック書き込み時の例外補足とクリーンアップ | - |
| TD-682 | `antigravity_pipeline.py` | L225 | 🔴 open | `except Exception as e:` | アトミック書き込み時の例外補足とクリーンアップ | - |
| TD-683 | `antigravity_pipeline.py` | L254 | 🔴 open | `except Exception as e:` | ファイル読み込み時の例外補足 | - |
| TD-684 | `antigravity_pipeline.py` | L284 | 🔴 open | `except Exception as e:` | SRTブロックパース時の例外補足 | - |
| TD-685 | `antigravity_pipeline.py` | L91 | 🔴 open | `except Exception as e:` | 個別具体的な例外キャッチへのリファクタリング | - |
| TD-686 | `antigravity_pipeline.py` | L100 | ✅ fixed | `except Exception:` | 個別具体的な例外キャッチへのリファクタリング | 2026-06-08 |
| TD-687 | `antigravity_pipeline.py` | L119 | 🔴 open | `except Exception as e:` | 個別具体的な例外キャッチへのリファクタリング | - |
| TD-688 | `antigravity_pipeline.py` | L143 | 🔴 open | `except Exception as e:` | 個別具体的な例外キャッチへのリファクタリング | - |
| TD-689 | `antigravity_pipeline.py` | L162 | 🔴 open | `except Exception as e:` | 個別具体的な例外キャッチへのリファクタリング | - |
| TD-690 | `antigravity_pipeline.py` | L189 | 🔴 open | `except Exception as e:` | 個別具体的な例外キャッチへのリファクタリング | - |
| TD-691 | `antigravity_pipeline.py` | L215 | 🔴 open | `except Exception as e:` | 個別具体的な例外キャッチへのリファクタリング | - |
| TD-692 | `antigravity_pipeline.py` | L245 | 🔴 open | `except Exception as e:` | 個別具体的な例外キャッチへのリファクタリング | - |
| TD-693 | `antigravity_pipeline.py` | L275 | ✅ fixed | `except Exception:` | 個別具体的な例外キャッチへのリファクタリング | 2026-06-08 |
| TD-694 | `antigravity_pipeline.py` | L286 | 🔴 open | `except Exception as e:` | 個別具体的な例外キャッチへのリファクタリング | - |
| TD-695 | `antigravity_pipeline.py` | L293 | 🔴 open | `except Exception as e:` | 個別具体的な例外キャッチへのリファクタリング | - |
| TD-696 | `antigravity_pipeline.py` | L299 | 🔴 open | `except Exception as e:` | 個別具体的な例外キャッチへのリファクタリング | - |
| TD-716 | `services/workspace_sync.py` | L106 | ✅ fixed | `except Exception as e:` |  | 2026-06-05 |
| TD-717 | `services/workspace_sync.py` | L148 | ✅ fixed | `except Exception as e:` |  | 2026-06-27 |
| TD-718 | `services/workspace_sync.py` | L208 | ✅ fixed | `except Exception as e:` |  | 2026-06-27 |
| TD-719 | `services/workspace_sync.py` | L372 | ✅ fixed | `except Exception as e:` |  | 2026-06-27 |
| TD-720 | `services/preflight_validator.py` | L75 | ✅ fixed | `except Exception as e:` | 各OSでの例外原因のログ分析およびハンドリング精査 | 2026-05-24 |
| TD-721 | `services/preflight_validator.py` | L84 | 🔴 open | `except Exception as e:` | 各OSでの例外原因のログ分析およびハンドリング精査 | - |
| TD-722 | `services/preflight_validator.py` | L95 | 🔴 open | `except Exception as e:` | 各OSでの例外原因のログ分析およびハンドリング精査 | - |
| TD-723 | `services/preflight_validator.py` | L106 | 🔴 open | `except Exception as e:` | 各OSでの例外原因のログ分析およびハンドリング精査 | - |
| TD-724 | `services/preflight_validator.py` | L140 | 🔴 open | `except Exception as e:` | 各OSでの例外原因のログ分析およびハンドリング精査 | - |
| TD-725 | `services/preflight_validator.py` | L152 | 🔴 open | `except Exception as e:` | 各OSでの例外原因のログ分析およびハンドリング精査 | - |
| TD-726 | `services/preflight_validator.py` | L162 | 🔴 open | `except Exception as e:` | 各OSでの例外原因のログ分析およびハンドリング精査 | - |
| TD-727 | `services/preflight_validator.py` | L172 | 🔴 open | `except Exception as e:` | 各OSでの例外原因のログ分析およびハンドリング精査 | - |
| TD-728 | `services/preflight_validator.py` | L205 | 🔴 open | `except Exception as e:` | 各OSでの例外原因のログ分析およびハンドリング精査 | - |
| TD-729 | `services/preflight_validator.py` | L215 | 🔴 open | `except Exception as e:` | 各OSでの例外原因のログ分析およびハンドリング精査 | - |
| TD-730 | `services/preflight_validator.py` | L225 | 🔴 open | `except Exception as e:` | 各OSでの例外原因のログ分析およびハンドリング精査 | - |
| TD-731 | `services/preflight_validator.py` | L281 | 🔴 open | `except Exception as e:` | 各OSでの例外原因のログ分析およびハンドリング精査 | - |
| TD-750 | `agents/orchestration/orchestrator.py` | L81 | ✅ fixed | `temp_path.unlink() in _write_json` | カバレッジ改善用の追加テストの実装 | 2026-06-08 |
| TD-751 | `agents/orchestration/orchestrator.py` | L250 | ✅ fixed | `except KeyError in _calculate_dynamic_limit` | カバレッジ改善用の追加テストの実装 | 2026-06-08 |
| TD-752 | `agents/orchestration/orchestrator.py` | L309 | ✅ fixed | `except Exception in _recover_timed_out_tasks` | カバレッジ改善用の追加テストの実装 | 2026-06-08 |
| TD-753 | `agents/orchestration/orchestrator.py` | L320 | ✅ fixed | `task.pop('assigned_agent') in _recover_timed_out_tasks` | カバレッジ改善用の追加テストの実装 | 2026-06-08 |
| TD-754 | `agents/orchestration/orchestrator.py` | L368 | ✅ fixed | `msg.get('content') in get_next_batch` | カバレッジ改善用の追加テストの実装 | 2026-06-08 |
| TD-755 | `agents/orchestration/orchestrator.py` | L383 | ✅ fixed | `except KeyError in get_next_batch` | カバレッジ改善用の追加テストの実装 | 2026-06-08 |
| TD-756 | `agents/orchestration/orchestrator.py` | L414 | ✅ fixed | `ts and (now - ts) > timedelta(minutes=30) in get_next_batch` | カバレッジ改善用の追加テストの実装 | 2026-06-08 |
| TD-757 | `agents/orchestration/orchestrator.py` | L448 | ✅ fixed | `except (json.JSONDecodeError, KeyError, TypeError, ValueError) in get_next_batch` | カバレッジ改善用の追加テストの実装 | 2026-06-08 |
| TD-758 | `agents/orchestration/orchestrator.py` | L463 | ✅ fixed | `except (ImportError, AttributeError) in get_next_batch` | カバレッジ改善用の追加テストの実装 | 2026-06-08 |
| TD-759 | `agents/orchestration/orchestrator.py` | L548 | ✅ fixed | `except Exception in mark_task_done` | カバレッジ改善用の追加テストの実装 | 2026-05-31 |
| TD-760 | `agents/orchestration/orchestrator.py` | L554 | ✅ fixed | `except Exception in mark_task_done (blacklist_module)` | カバレッジ改善用の追加テストの実装 | 2026-06-08 |
| TD-761 | `agents/orchestration/orchestrator.py` | L574 | ✅ fixed | `get_queue_status method` | カバレッジ改善用の追加テストの実装 | 2026-06-08 |
| TD-762 | `agents/orchestration/orchestrator.py` | L690 | ✅ fixed | `except (json.JSONDecodeError, KeyError, TypeError, ValueError) in submit_batch_report` | カバレッジ改善用の追加テストの実装 | 2026-06-08 |
| TD-763 | `agents/orchestration/orchestrator.py` | L740 | ✅ fixed | `except Exception in submit_batch_report (git)` | カバレッジ改善用の追加テストの実装 | 2026-06-08 |
| TD-764 | `agents/orchestration/orchestrator.py` | L758 | ✅ fixed | `except Exception in submit_batch_report (inbox report)` | カバレッジ改善用の追加テストの実装 | 2026-06-08 |
| TD-765 | `agents/orchestration/orchestrator.py` | L764 | ✅ fixed | `except Exception in submit_batch_report (hourly report)` | カバレッジ改善用の追加テストの実装 | 2026-06-08 |
| TD-766 | `agents/orchestration/orchestrator.py` | L770 | ✅ fixed | `except Exception in submit_batch_report (dashboard)` | カバレッジ改善用の追加テストの実装 | 2026-06-08 |
| TD-767 | `agents/orchestration/orchestrator.py` | L802 | ✅ fixed | `set_directive method` | カバレッジ改善用の追加テストの実装 | 2026-06-08 |
| TD-768 | `agents/orchestration/orchestrator.py` | L829 | ✅ fixed | `should_trigger_opus_review method` | カバレッジ改善用の追加テストの実装 | 2026-06-08 |
| TD-769 | `agents/orchestration/orchestrator.py` | L876 | ✅ fixed | `trigger_opus_review_now method` | カバレッジ改善用の追加テストの実装 | 2026-06-08 |
| TD-770 | `agents/orchestration/orchestrator.py` | L887 | ✅ fixed | `start_opus_review method` | カバレッジ改善用の追加テストの実装 | 2026-06-08 |
| TD-771 | `agents/orchestration/orchestrator.py` | L932 | ✅ fixed | `end_opus_review method` | カバレッジ改善用の追加テストの実装 | 2026-06-08 |
| TD-772 | `agents/orchestration/orchestrator.py` | L1032 | ✅ fixed | `blacklist_module method` | カバレッジ改善用の追加テストの実装 | 2026-06-08 |
| TD-773 | `agents/orchestration/orchestrator.py` | L1050 | ✅ fixed | `unblacklist_module method` | カバレッジ改善用の追加テストの実装 | 2026-06-08 |
| TD-774 | `agents/orchestration/orchestrator.py` | L1070 | ✅ fixed | `trigger_emergency_stop method` | カバレッジ改善用の追加テストの実装 | 2026-06-08 |
| TD-775 | `agents/orchestration/orchestrator.py` | L1084 | ✅ fixed | `resume_from_stop method` | カバレッジ改善用の追加テストの実装 | 2026-06-08 |
| TD-776 | `agents/orchestration/orchestrator.py` | L1142 | ✅ fixed | `flash_update_status parameters` | カバレッジ改善用の追加テストの実装 | 2026-06-08 |
| TD-777 | `agents/orchestration/orchestrator.py` | L1177 | ✅ fixed | `flash_heartbeat auto-recovery` | カバレッジ改善用の追加テストの実装 | 2026-06-01 |
| TD-778 | `agents/orchestration/orchestrator.py` | L1214 | ✅ fixed | `flash_update_heartbeat auto-recovery` | カバレッジ改善用の追加テストの実装 | 2026-06-01 |
| TD-779 | `agents/orchestration/orchestrator.py` | L1314 | ✅ fixed | `diagnose_flash_issues exit_reason` | カバレッジ改善用の追加テストの実装 | 2026-06-08 |
| TD-780 | `agents/orchestration/orchestrator.py` | L1343 | ✅ fixed | `diagnose_flash_issues progress` | カバレッジ改善用の追加テストの実装 | 2026-06-08 |
| TD-781 | `agents/orchestration/orchestrator.py` | L1352 | ✅ fixed | `diagnose_flash_issues emergency_stop` | カバレッジ改善用の追加テストの実装 | 2026-06-08 |
| TD-782 | `agents/orchestration/orchestrator.py` | L1378 | ✅ fixed | `send_improvement_directive method` | カバレッジ改善用の追加テストの実装 | 2026-06-08 |
| TD-783 | `agents/orchestration/orchestrator.py` | L1395 | ✅ fixed | `generate_flash_status method` | カバレッジ改善用の追加テストの実装 | 2026-06-08 |
| TD-784 | `agents/orchestration/orchestrator.py` | L1548 | ✅ fixed | `generate_status_summary method` | カバレッジ改善用の追加テストの実装 | 2026-06-08 |
| TD-785 | `agents/orchestration/orchestrator.py` | L1653 | ✅ fixed | `_generate_batch_report_file details` | カバレッジ改善用の追加テストの実装 | 2026-06-08 |
| TD-786 | `agents/orchestration/orchestrator.py` | L1758 | ✅ fixed | `_generate_phase_report helper functions` | カバレッジ改善用の追加テストの実装 | 2026-06-08 |
| TD-787 | `agents/orchestration/orchestrator.py` | L1868 | ✅ fixed | `_generate_phase_report metrics` | カバレッジ改善用の追加テストの実装 | 2026-06-08 |
| TD-788 | `agents/orchestration/orchestrator.py` | L1915 | ✅ fixed | `_generate_phase_report fallback` | カバレッジ改善用の追加テストの実装 | 2026-06-08 |
| TD-789 | `agents/orchestration/orchestrator.py` | L2006 | ✅ fixed | `_generate_phase_report decisions` | カバレッジ改善用の追加テストの実装 | 2026-06-08 |
| TD-790 | `agents/orchestration/orchestrator.py` | L2063 | ✅ fixed | `_generate_phase_report manual decision info` | カバレッジ改善用の追加テストの実装 | 2026-06-08 |
| TD-791 | `agents/orchestration/orchestrator.py` | L2108 | ✅ fixed | `_generate_phase_report decision categorization` | カバレッジ改善用の追加テストの実装 | 2026-06-08 |
| TD-792 | `agents/orchestration/orchestrator.py` | L2212 | ✅ fixed | `_generate_phase_report group stats` | カバレッジ改善用の追加テストの実装 | 2026-06-08 |
| TD-793 | `agents/orchestration/orchestrator.py` | L2500 | ✅ fixed | `Uncovered regions from line 2500 onwards` | カバレッジ改善用の追加テストの実装 | 2026-06-08 |
| TD-810 | `routers/trinity.py` | L23 | ✅ fixed | `except Exception as e:` | Router層catch-all: HTTPExceptionガード配置済み、TDR静的登録 | 2026-06-23 |
| TD-811 | `routers/trinity.py` | L50 | 🔴 open | `except Exception as e:` | Router層catch-all: HTTPExceptionガード配置済み、TDR静的登録 | - |
| TD-812 | `routers/trinity.py` | L85 | 🔴 open | `except Exception as e:` | Router層catch-all: HTTPExceptionガード配置済み、TDR静的登録 | - |
| TD-813 | `routers/trinity.py` | L112 | 🔴 open | `except Exception as e:` | Router層catch-all: HTTPExceptionガード配置済み、TDR静的登録 | - |
| TD-814 | `routers/trinity.py` | L139 | 🔴 open | `except Exception as e:` | Router層catch-all: HTTPExceptionガード配置済み、TDR静的登録 | - |
| TD-815 | `routers/trinity.py` | L172 | 🔴 open | `except Exception as e:` | Router層catch-all: HTTPExceptionガード配置済み、TDR静的登録 | - |
| TD-816 | `routers/trinity.py` | L203 | 🔴 open | `except Exception as e:` | Router層catch-all: HTTPExceptionガード配置済み、TDR静的登録 | - |
| TD-817 | `routers/trinity.py` | L249 | 🔴 open | `except Exception as e:` | Router層catch-all: HTTPExceptionガード配置済み、TDR静的登録 | - |
| TD-818 | `routers/trinity.py` | L283 | 🔴 open | `except Exception as e:` | Router層catch-all: HTTPExceptionガード配置済み、TDR静的登録 | - |
| TD-819 | `routers/trinity.py` | L317 | 🔴 open | `except Exception as e:` | Router層catch-all: HTTPExceptionガード配置済み、TDR静的登録 | - |
| TD-820 | `routers/trinity.py` | L354 | 🔴 open | `except Exception as e:` | Router層catch-all: HTTPExceptionガード配置済み、TDR静的登録 | - |
| TD-821 | `routers/trinity.py` | L390 | 🔴 open | `except Exception as e:` | Router層catch-all: HTTPExceptionガード配置済み、TDR静的登録 | - |
| TD-827 | `agents/workers/quality_gate_worker.py` | L258 | ✅ fixed | `except Exception as e:` | 適切な例外捕捉またはログ出力 | 2026-06-03 |
| TD-850 | `trim_segments.py` | L144 | ✅ fixed | `except Exception as e:` | Review exception handling | 2026-06-23 |
| TD-899 | `screenshot_generator.py` | L36 | ✅ fixed | `except Exception as e:` | 特定の例外（subprocess.SubprocessError, ValueError）への限定、またはロギングによる安全ネットとしての許容 | 2026-06-02 |
| TD-906 | `subtitle_preview.py` | L143 | 🔴 open | `except Exception as e:` |  | - |
| TD-907 | `subtitle_preview.py` | L298 | 🔴 open | `except Exception as e:` |  | - |
| TD-908 | `subtitle_preview.py` | L374 | 🔴 open | `except Exception as e:` |  | - |
| TD-909 | `subtitle_preview.py` | L138 | 🔴 open | `validate_image_properties try-except block` |  | - |
| TD-910 | `subtitle_preview.py` | L271 | 🔴 open | `Pillow ImageEnhance / Atomic Write try-except block` |  | - |
| TD-911 | `subtitle_preview.py` | L350 | 🔴 open | `resolve_subtitle_preview_task try-except block` |  | - |
| TD-912 | `preview_engine.py` | L468 | 🔵 accepted | `except Exception as e: (in generate_thumbnail)` | フォールバックグラデーション生成のための安全ネット | 2026-05-31 |
| TD-913 | `preview_engine.py` | L549 | 🔵 accepted | `except Exception as e: (in img.verify())` | Pillow画像破損検証例外キャッチ | 2026-05-31 |
| TD-914 | `tests/scratch/migrate_e2e_files.py` | L27 | ✅ fixed | `except Exception as e:` | try...exceptによるIOErrorの安全なハンドリングと警告出力の追加 | 2026-05-31 |
| TD-919 | `comprehensive_preview.py` | L113 | ✅ fixed | `except Exception:` | 安全フォールバックのための例外キャッチ | 2026-06-08 |
| TD-921 | `preview_engine.py` | L480 | 🔴 open | `except Exception as e: (in generate_thumbnail)` | フォールバックグラデーション生成のための安全ネット | - |
| TD-925 | `plugins/report_generator_plugin.py` | L117 | ✅ fixed | `import json` | モジュール先頭にインポートを移動 | 2026-06-01 |
| TD-926 | `progressive_preview_report.py` | L888 | 🔴 open | `except Exception as e:` | 特定の例外(OSErrorなど)に限定するか、上位へ再スローする | - |
| TD-927 | `progressive_preview_report.py` | L915 | ✅ fixed | `except (UnidentifiedImageError, Exception) as e:` | Pillow専用の例外ハンドリングに限定する | 2026-06-08 |
| TD-928 | `progressive_preview_report.py` | L923 | 🔴 open | `except Exception as e:` | ピクセルデータロード時の例外ハンドリングに限定する | - |
| TD-931 | `preview_engine.py` | L505 | 🔴 open | `except Exception as e: (in generate_thumbnail)` | フォールバックグラデーション生成のための安全ネット | - |
| TD-936 | `transcribe_simple.py` | L44 | ✅ fixed | `except Exception as e:` | WhisperModelロード時の詳細エラーハンドリング | 2026-06-05 |
| TD-937 | `transcribe_simple.py` | L70 | ✅ fixed | `except Exception as e:` | Whisper文字起こし中の詳細エラーハンドリング | 2026-06-05 |
| TD-938 | `transcribe_simple.py` | L115 | ✅ fixed | `except Exception as e:` | メインブロックにおける予期せぬ例外のフォールバック | 2026-06-05 |
| TD-946 | `agents/orchestration/mark_timeout_fail.py` | L41 | ✅ fixed | `except Exception as e` | 具体的例外クラスに限定 | 2026-06-08 |
| TD-947 | `agents/orchestration/mark_timeout_fail.py` | L47 | ✅ fixed | `except Exception as e` | 具体的例外クラスに限定 | 2026-06-08 |
| TD-948 | `agents/orchestration/mark_timeout_fail.py` | L67 | ✅ fixed | `except Exception as e` | 具体的例外クラスに限定 | 2026-06-08 |
| TD-949 | `agents/orchestration/mark_timeout_fail.py` | L74 | ✅ fixed | `except Exception as e` | 具体的例外クラスに限定 | 2026-06-08 |
| TD-950 | `agents/orchestration/mark_timeout_fail.py` | L114 | ✅ fixed | `except Exception as e` | 具体的例外クラスに限定 | 2026-06-08 |
| TD-951 | `agents/orchestration/mark_timeout_fail.py` | L119 | ✅ fixed | `except Exception as e` | 具体的例外クラスに限定 | 2026-06-08 |

---

## MINOR_INFRA: インフラ層（ログ出力あり） (640件 / open:257 fixed:333)

| ID | ファイル | 行 | ステータス | パターン | 修正パターン | 修正日 |
|:--|:---|:---:|:---:|:---|:---|:---|
| TD-1000 | `main.py` | L124 | ✅ fixed | `except Exception as e:` | 例外のログ記録、またはTDR自動登録時の例外キャッチ。 | 2026-06-27 |
| TD-1001 | `main.py` | L135 | ✅ fixed | `except Exception:` | 例外のログ記録、またはTDR自動登録時の例外キャッチ。 | 2026-06-27 |
| TD-1002 | `main.py` | L142 | ✅ fixed | `except Exception as e:` | 例外のログ記録、またはTDR自動登録時の例外キャッチ。 | 2026-06-27 |
| TD-1003 | `main.py` | L288 | ✅ fixed | `except Exception as e:` | 例外のログ記録、またはTDR自動登録時の例外キャッチ。 | 2026-06-27 |
| TD-1004 | `plugins/thumbnail_plugin.py` | L188 | ✅ fixed | `except Exception as ce:` | 一時ファイル削除失敗時の例外捕捉（ログ出力ありのためMINOR_INFRA） | 2026-06-27 |
| TD-1005 | `verified_preview_generator.py` | L262 | ✅ fixed | `except Exception as fe_draw:` | フォールバック時のテキスト描画失敗例外捕捉（ログ出力あり） | 2026-06-05 |
| TD-1006 | `verified_preview_generator.py` | L286 | ✅ fixed | `except Exception as e:` | フォルダ作成失敗の例外捕捉（ログ出力あり） | 2026-06-05 |
| TD-1007 | `services/thumbnail_analyzer.py` | L657 | ✅ fixed | `except Exception as ex:` | 一時ファイル移動失敗時の例外捕捉（ログ出力ありのためMINOR_INFRA） | 2026-06-08 |
| TD-1013 | `agents/orchestration/flash_runner_next_batch_5.py` | L29 | ✅ fixed | `except Exception as e:` | 特定の例外ハンドリングに置き換え | 2026-06-07 |
| TD-1037 | `add_premium_branding.py` | L337 | 🔴 open | `except Exception as e:` |  | - |
| TD-1038 | `add_premium_branding.py` | L559 | 🔴 open | `except Exception as e:` |  | - |
| TD-1050 | `agents/orchestration/init_check.py` | L45 | 🔴 open | `except Exception as e:` | CLI entrypoint exception handler (sys.exit) | - |
| TD-1055 | `scratch/mark_tasks_f076d6_000_001_done.py` | L1228 | 🔴 open | `except Exception as e:` |  | - |
| TD-1056 | `scratch/mark_tasks_f076d6_000_001_done.py` | L100 | 🔴 open | `except Exception as e:` |  | - |
| TD-1059 | `plugins/music_layer_plugin.py` | L105 | ✅ fixed | `except Exception as e:` | 具体例外型(AttributeError, TypeError, KeyError)への変更、または安全ネットとしての存続 | 2026-06-07 |
| TD-1060 | `whisper_transcriber.py` | L231 | 🔴 open | `except Exception as e:` | 適切に例外をログして再スローまたは安全に終了 | - |
| TD-1061 | `agents/orchestration/dispatch_next_batch.py` | L32 | 🔴 open | `except Exception as register_err:` | Replace with specific exception | - |
| TD-1062 | `agents/agent_base.py` | L13 | ✅ fixed | `import google.adk / import model_registry (fallback)` | テスト時のモジュールロード分離 | 2026-06-08 |
| TD-1063 | `agents/agent_base.py` | L176 | ✅ fixed | `def process(self, ...): pass` | 抽象定義のため修正不要（Accepted化推奨） | 2026-06-08 |
| TD-1064 | `agents/orchestration/copy_artifacts2.py` | L48 | ✅ fixed | `except Exception as e:` |  | 2026-06-23 |
| TD-1067 | `agents/orchestration/flash_status_update.py` | L66 | ✅ fixed | `except Exception as e:` | 具体的な例外の捕捉またはロギングの洗練 | 2026-06-07 |
| TD-1069 | `agents/orchestration/health_check_v2.py` | L63 | 🔵 accepted | `        except Exception:` |  | 2026-06-14 |
| TD-1070 | `agents/orchestration/health_check_v2.py` | L91 | 🔵 accepted | `    except Exception:` |  | 2026-06-14 |
| TD-1071 | `agents/orchestration/health_check_v2.py` | L161 | 🔵 accepted | `    except Exception:` |  | 2026-06-14 |
| TD-1072 | `agents/orchestration/health_check_v2.py` | L185 | 🔵 accepted | `        except Exception:` |  | 2026-06-14 |
| TD-1073 | `agents/orchestration/health_check_v2.py` | L343 | 🔵 accepted | `    except Exception as e:` |  | 2026-06-14 |
| TD-1074 | `agents/orchestration/health_check_v2.py` | L380 | 🔵 accepted | `    except Exception:` |  | 2026-06-14 |
| TD-1075 | `agents/orchestration/health_check_v2.py` | L641 | 🔵 accepted | `        except Exception:` |  | 2026-06-14 |
| TD-1076 | `agents/orchestration/health_check_v2.py` | L743 | 🔵 accepted | `    except Exception:` |  | 2026-06-14 |
| TD-1077 | `agents/orchestration/health_check_v2.py` | L846 | 🔵 accepted | `    except Exception:` |  | 2026-06-14 |
| TD-1078 | `agents/orchestration/health_check_v2.py` | L862 | 🔵 accepted | `        except Exception:` |  | 2026-06-14 |
| TD-1079 | `agents/orchestration/health_check_v2.py` | L886 | 🔵 accepted | `        except Exception:` |  | 2026-06-14 |
| TD-1080 | `agents/orchestration/health_check_v2.py` | L933 | 🔵 accepted | `    except Exception as e:` |  | 2026-06-14 |
| TD-1081 | `agents/orchestration/health_check_v2.py` | L947 | 🔵 accepted | `        except Exception:` |  | 2026-06-14 |
| TD-1082 | `agents/orchestration/health_check_v2.py` | L1107 | 🔵 accepted | `    except Exception:` |  | 2026-06-14 |
| TD-1083 | `agents/orchestration/health_check_v2.py` | L1174 | 🔵 accepted | `        except Exception as e:` |  | 2026-06-14 |
| TD-1084 | `agents/orchestration/health_check_v2.py` | L1196 | 🔵 accepted | `        except Exception:` |  | 2026-06-14 |
| TD-1085 | `agents/orchestration/health_check_v2.py` | L1208 | 🔵 accepted | `            except Exception as e:` |  | 2026-06-14 |
| TD-1086 | `agents/orchestration/health_check_v2.py` | L1220 | 🔵 accepted | `            except Exception as ae:` |  | 2026-06-14 |
| TD-1087 | `agents/orchestration/health_check_v2.py` | L1226 | 🔵 accepted | `        except Exception as e:` |  | 2026-06-14 |
| TD-1088 | `agents/orchestration/orchestrator_v2.py` | L81 | 🔵 accepted | `        except Exception as e:` |  | 2026-06-14 |
| TD-1089 | `agents/orchestration/orchestrator_v2.py` | L96 | 🔵 accepted | `        except Exception as e:` |  | 2026-06-14 |
| TD-1090 | `agents/orchestration/orchestrator_v2.py` | L166 | 🔵 accepted | `        except Exception as e:` |  | 2026-06-14 |
| TD-1091 | `agents/orchestration/orchestrator_v2.py` | L177 | 🔵 accepted | `        except Exception as e:` |  | 2026-06-14 |
| TD-1092 | `agents/memory/council_decision_extractor.py` | L166 | ✅ fixed | `# 1. 技術負債に自動登録（新規 except Exception の追加に準拠）` | Specific exception handling or explicit logging | 2026-06-08 |
| TD-1093 | `agents/memory/council_decision_extractor.py` | L178 | ✅ fixed | `except Exception as e:` | Specific exception handling or explicit logging | 2026-06-27 |
| TD-1094 | `agents/memory/council_decision_extractor.py` | L193 | ✅ fixed | `except Exception as e:` | Specific exception handling or explicit logging | 2026-06-27 |
| TD-1095 | `agents/memory/council_decision_extractor.py` | L379 | ✅ fixed | `except Exception as e:` | Specific exception handling or explicit logging | 2026-06-27 |
| TD-1096 | `agents/nexus_council_v3.py` | L263 | 🔴 open | `except Exception as extractor_err:` | Specific exception handling or explicit logging | - |
| TD-1097 | `agents/nexus_council_v3.py` | L279 | ✅ fixed | `except Exception as e:` | Specific exception handling or explicit logging | 2026-06-27 |
| TD-1098 | `agents/nexus_council_v3.py` | L291 | 🔴 open | `except Exception as extractor_err:` | Specific exception handling or explicit logging | - |
| TD-1099 | `agents/orchestration/directive_auto_updater.py` | L69 | ✅ fixed | `except Exception as e:` | Specific exception handling or explicit logging | 2026-06-23 |
| TD-1100 | `agents/orchestration/ds_task_decomposer.py` | L204 | ✅ fixed | `except Exception as e:` | Specific exception handling or explicit logging | 2026-06-23 |
| TD-1101 | `agents/orchestration/learning_integration.py` | L38 | ✅ fixed | `except Exception as e:` | Specific exception handling or explicit logging | 2026-06-07 |
| TD-1102 | `agents/orchestration/learning_integration.py` | L51 | ✅ fixed | `except Exception as e:` | Specific exception handling or explicit logging | 2026-06-07 |
| TD-1103 | `agents/orchestration/learning_integration.py` | L65 | ✅ fixed | `except Exception as e:` | Specific exception handling or explicit logging | 2026-06-07 |
| TD-1104 | `agents/orchestration/learning_integration.py` | L80 | ✅ fixed | `except Exception as e:` | Specific exception handling or explicit logging | 2026-06-07 |
| TD-1105 | `agents/orchestration/task_learning_engine.py` | L343 | ✅ fixed | `except Exception as e:` | Specific exception handling or explicit logging | 2026-06-28 |
| TD-1108 | `agents/orchestration/inline_coverage_extender.py` | L68 | 🔴 open | `except Exception:` | 一時ファイル削除等のアトミック書き込み安全ネットのためaccepted化を検討 | - |
| TD-1109 | `agents/orchestration/inline_coverage_extender.py` | L130 | 🔴 open | `except Exception as e:` | バックアップ復元・例外再送出の安全ネットのためaccepted化を検討 | - |
| TD-1110 | `agents/orchestration/inline_coverage_extender.py` | L236 | 🔴 open | `except Exception as e:` | バックアップ復元・例外再送出の安全ネットのためaccepted化を検討 | - |
| TD-1155 | `agents/orchestration/flash_assign_subagents_17.py` | L13 | ✅ fixed | `except Exception as e:` | None | 2026-06-07 |
| TD-1156 | `agents/orchestration/flash_assign_subagents_17.py` | L25 | ✅ fixed | `except Exception as e:` | None | 2026-06-07 |
| TD-1157 | `agents/orchestration/flash_assign_subagents_17.py` | L46 | ✅ fixed | `except Exception as e:` | None | 2026-06-07 |
| TD-1158 | `agents/orchestration/flash_assign_subagents_17.py` | L59 | ✅ fixed | `except Exception as e:` | None | 2026-06-07 |
| TD-1159 | `agents/orchestration/flash_assign_subagents_17.py` | L82 | ✅ fixed | `except Exception as e:` | None | 2026-06-07 |
| TD-1160 | `agents/orchestration/cooldown_handler.py` | L27 | ✅ fixed | `except Exception as e:` | None | 2026-06-07 |
| TD-1161 | `agents/orchestration/cooldown_handler.py` | L46 | ✅ fixed | `except Exception:` | None | 2026-06-07 |
| TD-1162 | `agents/orchestration/dynamic_decomposer.py` | L43 | ✅ fixed | `except Exception:` | None | 2026-06-23 |
| TD-1164 | `scratch/mark_task_29_done.py` | L26 | 🔵 accepted | `except Exception as e:` | 呼び出し元への例外伝播とログ出力 | 2026-06-07 |
| TD-1165 | `scratch/mark_task_29_done.py` | L33 | 🔵 accepted | `except Exception:` | スクリプトのエラー終了 | 2026-06-07 |
| TD-1172 | `agents/workers/quality_gate_worker.py` | L96 | 🔴 open | `except Exception as e: in execute (plugin run)` | プラグインエラーのハンドリングとフォールバック | - |
| TD-1174 | `agents/orchestration/mark_tasks_p27_bug_hunter_b88.py` | L155 | ✅ fixed | `except Exception as e:` | 例外の厳密な個別型ハンドリングとバリデーションを適用する | 2026-06-07 |
| TD-1175 | `agents/workers/quality_gate_worker.py` | L96 | 🔴 open | `except Exception as e: in execute (plugin run)` | プラグインエラーのハンドリングとフォールバック | - |
| TD-1176 | `agents/workers/quality_gate_worker.py` | L96 | 🔴 open | `except Exception as e: in execute (plugin run)` | プラグインエラーのハンドリングとフォールバック | - |
| TD-1177 | `agents/orchestration/dynamic_workflow_engine.py` | L132 | 🔴 open | `except Exception as e:` |  | - |
| TD-1178 | `agents/orchestration/dynamic_workflow_engine.py` | L142 | 🔴 open | `except Exception as e:` |  | - |
| TD-1179 | `agents/orchestration/dynamic_workflow_engine.py` | L170 | 🔴 open | `except Exception as e:` |  | - |
| TD-1180 | `agents/orchestration/dynamic_workflow_engine.py` | L186 | 🔴 open | `except Exception:` |  | - |
| TD-1181 | `agents/orchestration/dynamic_workflow_engine.py` | L230 | 🔴 open | `except Exception:` |  | - |
| TD-1182 | `agents/orchestration/workflow_checkpoint.py` | L153 | ✅ fixed | `except Exception:` |  | 2026-06-27 |
| TD-1183 | `agents/workers/quality_gate_worker.py` | L92 | ✅ fixed | `except Exception as e: in execute (template_config import)` | template_configインポート失敗のハンドリングとフォールバック | 2026-06-08 |
| TD-1184 | `agents/workers/quality_gate_worker.py` | L88 | 🔴 open | `except Exception as e: in execute (thumbnail physical check)` | サムネイル物理検証のエラーハンドリングと安全なスキップ | - |
| TD-1185 | `agents/workers/quality_gate_worker.py` | L126 | 🔴 open | `except ImportError as e: in execute (template_config import)` | template_configインポート失敗のハンドリングとフォールバック | - |
| TD-1188 | `agents/orchestration/mark_tasks_p27_bug_hunter_b88.py` | L120 | ✅ fixed | `except Exception as e:` | 例外の厳密な個別型ハンドリングとバリデーションを適用する | 2026-06-07 |
| TD-1189 | `cleanup_manager.py` | L405 | ✅ fixed | `except Exception as e:` | 個別例外の分離または適切な例外伝播 | 2026-06-07 |
| TD-1190 | `cleanup_manager.py` | L422 | ✅ fixed | `except Exception as e:` | 個別例外の分離または適切な例外伝播 | 2026-06-07 |
| TD-1191 | `cleanup_manager.py` | L432 | 🔵 accepted | `except Exception as e:` | 個別例外の分離または適切な例外伝播 | 2026-06-07 |
| TD-1192 | `cleanup_manager.py` | L447 | ✅ fixed | `except Exception as e:` | 個別例外の分離または適切な例外伝播 | 2026-06-07 |
| TD-1193 | `cleanup_manager.py` | L477 | ✅ fixed | `except Exception as e:` | 個別例外の分離または適切な例外伝播 | 2026-06-07 |
| TD-1194 | `cleanup_manager.py` | L521 | ✅ fixed | `except Exception as e:` | 個別例外の分離または適切な例外伝播 | 2026-06-07 |
| TD-1195 | `agents/orchestration/copy_artifacts_batch_449dfb.py` | L88 | ✅ fixed | `except Exception as e:` | 具体的な例外をキャッチするように修正 | 2026-06-07 |
| TD-1196 | `agents/orchestration/flash_assign_subagents_5.py` | L64 | ✅ fixed | `except Exception as e:` | 個別例外の分離または適切な例外伝播 | 2026-06-07 |
| TD-1206 | `agents/orchestration/flash_assign_subagents_5.py` | L72 | ✅ fixed | `except Exception as e:` | 安全ネットとして残す（ログとトレースバックを出力して終了） | 2026-06-07 |
| TD-1207 | `agents/orchestration/resource_governor.py` | L32 | 🔴 open | `except Exception:` | except (FileNotFoundError, json.JSONDecodeError): などへの詳細化 | - |
| TD-1208 | `agents/orchestration/flash_assign_subagents_17.py` | L41 | ✅ fixed | `except Exception as e:` | OrchestrationHub の heartbeat 更新時の予期せぬ例外キャッチのままとするか、あるいは上位伝播に任せる | 2026-06-07 |
| TD-1211 | `agents/orchestration/generate_flash_prompt.py` | L357 | 🔵 accepted | `except Exception as e:` |  | 2026-06-07 |
| TD-1220 | `agents/orchestration/dispatch_next_batch.py` | L175 | 🔴 open | `dispatch_next_batch.main` | 例外の厳密な個別型ハンドリングとバリエーションを適用する | - |
| TD-1221 | `cleanup_manager.py` | L555 | 🔴 open | `except Exception as e:` | 想定外例外（JSONパース時など）の安全なwarningログキャッチ | - |
| TD-1229 | `model_governance_local.py` | L286 | ✅ fixed | `except Exception as e:` | Keep as safety net for background loop resilience, log errors with traceback | 2026-06-27 |
| TD-1230 | `agents/orchestration/heartbeat_only.py` | L40 | ✅ fixed | `except Exception as e:` |  | 2026-06-23 |
| TD-1233 | `agents/orchestration/mark_tasks_multi.py` | L133 | ✅ fixed | `except Exception as e:` | 具体的な例外に分解する | 2026-06-27 |
| TD-1234 | `scratch/dispatch_next_batch_2.py` | L53 | 🔴 open | `except Exception as e:` | 例外の厳密な個別型ハンドリングとバリデーションを適用する | - |
| TD-1235 | `scratch/dispatch_next_batch_2.py` | L66 | 🔴 open | `except Exception as e:` | 例外の厳密な個別型ハンドリングとバリデーションを適用する | - |
| TD-1236 | `scratch/dispatch_next_batch_2.py` | L99 | 🔴 open | `except Exception as e:` | 例外の厳密な個別型ハンドリングとバリデーションを適用する | - |
| TD-1237 | `scratch/dispatch_next_batch_2.py` | L118 | 🔴 open | `except Exception as e:` | 例外の厳密な個別型ハンドリングとバリデーションを適用する | - |
| TD-1238 | `scratch/dispatch_next_batch_2.py` | L146 | 🔴 open | `except Exception as e:` | 例外の厳密な個別型ハンドリングとバリデーションを適用する | - |
| TD-1244 | `agents/orchestration/assign_task_agents.py` | L11 | ✅ fixed | `except Exception as e:` |  | 2026-06-27 |
| TD-1245 | `agents/orchestration/assign_task_agents.py` | L17 | ✅ fixed | `except Exception as e:` |  | 2026-06-27 |
| TD-1246 | `agents/orchestration/flash_submit_batch.py` | L29 | ✅ fixed | `except Exception:` |  | 2026-06-27 |
| TD-1258 | `agents/orchestration/research_reporter.py` | L73 | ✅ fixed | `except Exception:` | 安全なフォールバックとしての例外キャッチ | 2026-06-27 |
| TD-1259 | `agents/orchestration/research_reporter.py` | L77 | ✅ fixed | `except Exception:` | 安全なフォールバックとしての例外キャッチ | 2026-06-27 |
| TD-1260 | `plugins/auto_chapters_plugin.py` | L169 | 🔴 open | `except Exception as e:` | プラグイン層での包括的な例外捕捉によるクラッシュ防止 | - |
| TD-1261 | `agents/orchestration/flash_mark_task.py` | L30 | ✅ fixed | `except Exception as e:` | 個別例外捕捉の適用、または正当な安全ネットとしての許容 | 2026-06-12 |
| TD-1266 | `add_scene04_telop.py` | L173 | ✅ fixed | `except Exception:` | 安全なフォールバック (ログ出力時の例外無視) | 2026-06-10 |
| TD-1275 | `agents/orchestration/run_batch_report.py` | L19 | ✅ fixed | `    except Exception as e:` | Fix exception handling in temporary script | 2026-06-27 |
| TD-1276 | `harness_audit_runner.py` | L221 | ✅ fixed | `except Exception as e:` | 自動例外処理とTDR登録 | 2026-06-27 |
| TD-1283 | `agents/orchestration/flash_assign_subagents_11.py` | L98 | ✅ fixed | `except Exception as e:` | Catch specific exceptions | 2026-06-15 |
| TD-1284 | `utils/evolution_log_migration.py` | L89 | 🔴 open | `except Exception as e:` | Catch specific exceptions | - |
| TD-1285 | `agents/orchestration/flash_assign_subagents.py` | L78 | ✅ fixed | `except Exception as e:` | エラーハンドリングのリファクタリング | 2026-06-23 |
| TD-1286 | `agents/orchestration/flash_assign_subagents_12.py` | L107 | ✅ fixed | `except Exception as e:` | エラーハンドリングのリファクタリング | 2026-06-15 |
| TD-1287 | `agents/orchestration/flash_assign_subagents_8.py` | L144 | ✅ fixed | `except Exception as e:` | エラーハンドリングのリファクタリング | 2026-06-12 |
| TD-1288 | `agents/orchestration/run_session_end.py` | L91 | ✅ fixed | `except Exception as e:` | エラーハンドリングのリファクタリング | 2026-06-12 |
| TD-1294 | `utils/json_safe_io.py` | L66 | ✅ fixed | `except Exception:` |  | 2026-06-15 |
| TD-1295 | `utils/json_safe_io.py` | L73 | ✅ fixed | `except Exception as e:` |  | 2026-06-15 |
| TD-1296 | `quality_gate_plugins.py` | L137 | ✅ fixed | `except Exception as e:` |  | 2026-06-27 |
| TD-1302 | `scratch/get_next_batch.py` | L75 | 🔴 open | `except Exception as e:` | 個別例外のキャッチまたは適切なエラー伝播へのリファクタ | - |
| TD-1403 | `agents/orchestration/check_active_agents.py` | L27 | ✅ fixed | `except Exception as e:` |  | 2026-06-15 |
| TD-1404 | `agents/orchestration/check_active_agents.py` | L45 | ✅ fixed | `except Exception as e:` |  | 2026-06-15 |
| TD-1431 | `agents/orchestration/flash_get_next_batch.py` | L61 | 🔴 open | `except Exception as e:` | より具体的な例外クラスへの限定、または堅牢なグローバルエラーハンドリングハンドラーへの統合 | - |
| TD-1432 | `agents/orchestration/stats_collector.py` | L34 | 🔴 open | `except Exception:` | ロギングを追加するか、特定の例外に置き換え | - |
| TD-1433 | `agents/orchestration/stats_collector.py` | L83 | 🔴 open | `except Exception:` | ロギングを追加するか、特定の例外に置き換え | - |
| TD-1434 | `agents/orchestration/stats_collector.py` | L141 | 🔴 open | `except Exception as e:` | ロギングを追加するか、特定の例外に置き換え | - |
| TD-1435 | `agents/orchestration/stats_collector.py` | L234 | 🔴 open | `except Exception as e:` | ロギングを追加するか、特定の例外に置き換え | - |
| TD-1436 | `agents/orchestration/stats_collector.py` | L297 | 🔴 open | `except Exception as e:` | ロギングを追加するか、特定の例外に置き換え | - |
| TD-1437 | `agents/orchestration/stats_collector.py` | L339 | 🔴 open | `except Exception as e:` | ロギングを追加するか、特定の例外に置き換え | - |
| TD-1438 | `agents/orchestration/stats_collector.py` | L508 | 🔴 open | `except Exception:` | ロギングを追加するか、特定の例外に置き換え | - |
| TD-1439 | `agents/orchestration/stats_collector.py` | L542 | 🔴 open | `except Exception:` | ロギングを追加するか、特定の例外に置き換え | - |
| TD-1441 | `agents/orchestration/mark_tasks_001.py` | L113 | ✅ fixed | `except Exception:` | 最外層の安全ネットとして TDR に登録 | 2026-06-27 |
| TD-1477 | `agents/orchestration/health_check_cron.py` | L264 | 🔴 open | `    except Exception:` |  | - |
| TD-1478 | `tests/test_smart_cut_engine.py` | L695 | 🔴 open | `@pytest.mark.xfail(reason="sys.path pollution from other tests or pytest-cov hook in smart_cut_engine", strict=False)` | Fix path resolution or decouple sys.path modification from test sequence | - |
| TD-254 | `agents/_deprecated/nexus.py` | L63 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-05 |
| TD-255 | `agents/_deprecated/nexus.py` | L124 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-05 |
| TD-256 | `agents/_deprecated/pipeline_coordinator.py` | L274 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-257 | `agents/_deprecated/pipeline_coordinator.py` | L312 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-258 | `agents/_deprecated/pipeline_coordinator.py` | L468 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-259 | `agents/_deprecated/pipeline_coordinator.py` | L557 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-260 | `agents/_deprecated/pipeline_coordinator.py` | L590 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-261 | `agents/_deprecated/pipeline_coordinator.py` | L718 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-262 | `agents/_deprecated/pipeline_coordinator.py` | L1183 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-263 | `agents/_deprecated/production_pipeline.py` | L108 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-22 |
| TD-264 | `agents/_deprecated/production_pipeline.py` | L128 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-22 |
| TD-265 | `agents/_deprecated/production_pipeline.py` | L179 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-22 |
| TD-266 | `agents/_deprecated/production_pipeline.py` | L215 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-22 |
| TD-267 | `agents/_deprecated/production_pipeline.py` | L254 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-22 |
| TD-268 | `agents/_deprecated/production_pipeline.py` | L289 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-22 |
| TD-269 | `agents/_deprecated/production_pipeline.py` | L335 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-22 |
| TD-270 | `agents/_deprecated/production_pipeline.py` | L552 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-22 |
| TD-271 | `agents/_deprecated/supervisor.py` | L81 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-272 | `agents/advisor_gate.py` | L260 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-25 |
| TD-273 | `agents/agent_base.py` | L56 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-274 | `agents/context_compressor.py` | L189 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-275 | `agents/context_compressor.py` | L412 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-276 | `agents/context_compressor.py` | L483 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-277 | `agents/context_resolver.py` | L29 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-23 |
| TD-278 | `agents/council_graph.py` | L198 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-06 |
| TD-279 | `agents/council_logger.py` | L47 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-02 |
| TD-280 | `agents/dream_engine.py` | L257 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-15 |
| TD-281 | `agents/dream_engine.py` | L454 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-15 |
| TD-282 | `agents/dream_engine.py` | L789 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-15 |
| TD-283 | `agents/expert_collaboration.py` | L83 | 🔵 accepted | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-25 |
| TD-284 | `agents/expert_collaboration.py` | L92 | 🔵 accepted | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-25 |
| TD-285 | `agents/expert_collaboration.py` | L138 | 🔵 accepted | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-25 |
| TD-286 | `agents/expert_collaboration.py` | L158 | 🔵 accepted | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-25 |
| TD-287 | `agents/memory/verified_facts.py` | L307 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-22 |
| TD-288 | `agents/memory/verified_facts.py` | L331 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-22 |
| TD-289 | `agents/memory/verified_facts.py` | L339 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-22 |
| TD-290 | `agents/pipeline_coordinator.py` | L178 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-291 | `agents/pipeline_coordinator.py` | L322 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-292 | `agents/pipeline_coordinator.py` | L361 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-293 | `agents/resolution_tracker.py` | L143 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-08 |
| TD-294 | `agents/strategist.py` | L98 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-28 |
| TD-295 | `agents/tick_loop.py` | L473 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-19 |
| TD-296 | `agents/workers/preview_worker.py` | L66 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-25 |
| TD-297 | `agents/workers/proofread_worker.py` | L56 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-298 | `agents/workers/proofread_worker.py` | L84 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-299 | `agents/workers/proofread_worker.py` | L121 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-300 | `agents/workers/render_worker.py` | L75 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-26 |
| TD-301 | `agents/workers/render_worker.py` | L138 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-26 |
| TD-302 | `agents/workers/render_worker.py` | L185 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-26 |
| TD-303 | `agents/workers/render_worker.py` | L205 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-26 |
| TD-304 | `agents/workers/render_worker.py` | L235 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-26 |
| TD-305 | `agents/workers/render_worker.py` | L249 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-26 |
| TD-306 | `agents/workers/render_worker.py` | L279 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-26 |
| TD-307 | `agents/workers/transcribe_worker.py` | L119 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-22 |
| TD-308 | `agents/workers/youtube_opt_worker.py` | L76 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-25 |
| TD-309 | `aligned_preview_generator.py` | L170 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-26 |
| TD-310 | `archives/archive_stable_v3.0_20260118_0953/director_engine.py` | L151 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-23 |
| TD-311 | `archives/archive_stable_v3.0_20260118_0953/director_engine.py` | L300 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-23 |
| TD-312 | `archives/archive_stable_v3.0_20260118_0953/director_engine.py` | L317 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-23 |
| TD-313 | `archives/archive_stable_v3.0_20260118_0953/director_engine.py` | L350 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-23 |
| TD-314 | `archives/archive_stable_v3.0_20260118_0953/director_engine.py` | L366 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-23 |
| TD-315 | `archives/archive_stable_v3.0_20260118_0953/director_engine.py` | L399 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-23 |
| TD-316 | `archives/archive_stable_v3.0_20260118_0953/director_engine.py` | L454 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-23 |
| TD-317 | `archives/archive_stable_v3.0_20260118_0953/director_engine.py` | L499 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-23 |
| TD-318 | `archives/archive_stable_v3.0_20260118_0953/director_engine.py` | L543 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-23 |
| TD-319 | `archives/archive_stable_v3.0_20260118_0953/director_engine.py` | L599 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-23 |
| TD-320 | `archives/archive_stable_v3.0_20260118_0953/director_engine.py` | L644 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-23 |
| TD-321 | `archives/archive_stable_v3.0_20260118_0953/director_engine.py` | L699 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-23 |
| TD-322 | `archives/archive_stable_v3.0_20260118_0953/generation_engine.py` | L120 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-07 |
| TD-323 | `archives/archive_stable_v3.0_20260118_0953/generation_engine.py` | L216 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-07 |
| TD-324 | `archives/archive_stable_v3.0_20260118_0953/generation_engine.py` | L286 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-07 |
| TD-325 | `archives/archive_stable_v3.0_20260118_0953/generation_engine.py` | L349 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-07 |
| TD-326 | `archives/archive_stable_v3.0_20260118_0953/learning_loop.py` | L99 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-327 | `archives/archive_stable_v3.0_20260118_0953/learning_loop.py` | L108 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-328 | `archives/archive_stable_v3.0_20260118_0953/learning_loop.py` | L119 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-329 | `archives/archive_stable_v3.0_20260118_0953/learning_loop.py` | L295 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-330 | `archives/archive_stable_v3.0_20260118_0953/main.py` | L149 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-331 | `archives/archive_stable_v3.0_20260118_0953/main.py` | L158 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-332 | `archives/archive_stable_v3.0_20260118_0953/main.py` | L172 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-333 | `archives/archive_stable_v3.0_20260118_0953/main.py` | L182 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-334 | `archives/archive_stable_v3.0_20260118_0953/main.py` | L206 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-335 | `archives/archive_stable_v3.0_20260118_0953/main.py` | L219 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-336 | `archives/archive_stable_v3.0_20260118_0953/main.py` | L228 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-337 | `archives/archive_stable_v3.0_20260118_0953/main.py` | L257 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-338 | `archives/archive_stable_v3.0_20260118_0953/main.py` | L271 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-339 | `archives/archive_stable_v3.0_20260118_0953/main.py` | L281 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-340 | `archives/archive_stable_v3.0_20260118_0953/main.py` | L319 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-341 | `archives/archive_stable_v3.0_20260118_0953/main.py` | L340 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-342 | `archives/archive_stable_v3.0_20260118_0953/main.py` | L357 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-343 | `archives/archive_stable_v3.0_20260118_0953/main.py` | L371 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-344 | `archives/archive_stable_v3.0_20260118_0953/main.py` | L385 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-345 | `archives/archive_stable_v3.0_20260118_0953/main.py` | L423 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-346 | `archives/archive_stable_v3.0_20260118_0953/main.py` | L463 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-347 | `archives/archive_stable_v3.0_20260118_0953/main.py` | L511 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-348 | `archives/archive_stable_v3.0_20260118_0953/main.py` | L534 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-349 | `archives/archive_stable_v3.0_20260118_0953/main.py` | L552 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-350 | `archives/archive_stable_v3.0_20260118_0953/main.py` | L595 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-351 | `archives/archive_stable_v3.0_20260118_0953/main.py` | L793 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-352 | `archives/archive_stable_v3.0_20260118_0953/main.py` | L889 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-353 | `archives/archive_stable_v3.0_20260118_0953/main.py` | L907 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-354 | `archives/archive_stable_v3.0_20260118_0953/main.py` | L926 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-355 | `archives/archive_stable_v3.0_20260118_0953/main.py` | L984 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-356 | `archives/archive_stable_v3.0_20260118_0953/main.py` | L1017 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-357 | `archives/archive_stable_v3.0_20260118_0953/main.py` | L1078 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-358 | `archives/archive_stable_v3.0_20260118_0953/main.py` | L1094 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-359 | `archives/archive_stable_v3.0_20260118_0953/main.py` | L1107 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-360 | `archives/archive_stable_v3.0_20260118_0953/main.py` | L1120 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-361 | `archives/archive_stable_v3.0_20260118_0953/main.py` | L1135 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-362 | `archives/archive_stable_v3.0_20260118_0953/main.py` | L1162 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-363 | `archives/archive_stable_v3.0_20260118_0953/main.py` | L1219 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-364 | `archives/archive_stable_v3.0_20260118_0953/main.py` | L1300 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-365 | `archives/archive_stable_v3.0_20260118_0953/main.py` | L1318 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-366 | `archives/archive_stable_v3.0_20260118_0953/main.py` | L1329 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-367 | `archives/archive_stable_v3.0_20260118_0953/main.py` | L1365 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-368 | `archives/archive_stable_v3.0_20260118_0953/main.py` | L1385 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-369 | `archives/archive_stable_v3.0_20260118_0953/main.py` | L1455 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-370 | `archives/archive_stable_v3.0_20260118_0953/main.py` | L1470 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-371 | `archives/archive_stable_v3.0_20260118_0953/main.py` | L1614 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-372 | `archives/archive_stable_v3.0_20260118_0953/main.py` | L1666 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-373 | `archives/archive_stable_v3.0_20260118_0953/main.py` | L1687 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-374 | `archives/archive_stable_v3.0_20260118_0953/main.py` | L1713 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-375 | `archives/archive_stable_v3.0_20260118_0953/main.py` | L1750 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-376 | `archives/archive_stable_v3.0_20260118_0953/main.py` | L1805 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-377 | `archives/archive_stable_v3.0_20260118_0953/main.py` | L1838 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-378 | `archives/archive_stable_v3.0_20260118_0953/main.py` | L1865 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-379 | `archives/archive_stable_v3.0_20260118_0953/main.py` | L1888 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-380 | `archives/archive_stable_v3.0_20260118_0953/main.py` | L1930 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-381 | `archives/archive_stable_v3.0_20260118_0953/main.py` | L1966 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-382 | `archives/archive_stable_v3.0_20260118_0953/main.py` | L1987 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-383 | `archives/archive_stable_v3.0_20260118_0953/main.py` | L2078 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-384 | `archives/archive_stable_v3.0_20260118_0953/main.py` | L2196 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-385 | `archives/archive_stable_v3.0_20260118_0953/quality_gate_agent.py` | L97 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-23 |
| TD-386 | `archives/archive_stable_v3.0_20260118_0953/self_review_engine.py` | L159 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-387 | `archives/archive_stable_v3.0_20260118_0953/self_review_engine.py` | L284 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-388 | `archives/archive_stable_v3.0_20260118_0953/video_processor.py` | L160 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-22 |
| TD-389 | `archives/archive_stable_v3.0_20260118_0953/video_processor.py` | L376 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-22 |
| TD-390 | `archives/archive_stable_v3.0_20260118_0953/video_processor.py` | L426 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-22 |
| TD-391 | `archives/unified/learning_unified.py` | L98 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-23 |
| TD-392 | `archives/unified/learning_unified.py` | L107 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-23 |
| TD-393 | `archives/unified/learning_unified.py` | L165 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-23 |
| TD-394 | `archives/unified/learning_unified.py` | L178 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-23 |
| TD-395 | `archives/unified/learning_unified.py` | L226 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-23 |
| TD-396 | `archives/unified/quality_unified.py` | L63 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-22 |
| TD-397 | `archives/unified/video_unified.py` | L125 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-07 |
| TD-398 | `archives/unified/video_unified.py` | L164 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-07 |
| TD-399 | `asset_library.py` | L202 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-24 |
| TD-400 | `asset_library.py` | L326 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-24 |
| TD-401 | `asset_library.py` | L534 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-24 |
| TD-402 | `auto_full_build.py` | L152 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-403 | `auto_full_build.py` | L180 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-404 | `auto_full_build.py` | L189 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-405 | `branding/history_manager.py` | L45 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-406 | `branding/history_manager.py` | L58 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-407 | `check_app.py` | L15 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-31 |
| TD-408 | `clean_rebuild.py` | L163 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-22 |
| TD-409 | `clean_rebuild.py` | L232 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-22 |
| TD-410 | `cleanup_manager.py` | L191 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-05 |
| TD-411 | `color_grading.py` | L110 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-07 |
| TD-412 | `combined_overlay.py` | L219 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-413 | `combined_overlay.py` | L224 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-414 | `combined_overlay.py` | L252 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-415 | `core/context.py` | L150 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-25 |
| TD-416 | `core/registry.py` | L102 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-23 |
| TD-417 | `core/registry.py` | L138 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-23 |
| TD-418 | `corrected_preview_generator.py` | L171 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-26 |
| TD-419 | `data_migration.py` | L120 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-08 |
| TD-420 | `design_system/design_chat_handler.py` | L163 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-22 |
| TD-421 | `design_system/design_token_manager.py` | L152 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-15 |
| TD-422 | `design_system/design_token_manager.py` | L255 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-15 |
| TD-423 | `design_system/design_token_manager.py` | L269 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-15 |
| TD-424 | `director_engine.py` | L149 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-425 | `director_engine.py` | L298 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-426 | `director_engine.py` | L315 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-427 | `director_engine.py` | L348 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-428 | `director_engine.py` | L364 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-429 | `director_engine.py` | L397 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-430 | `director_engine.py` | L452 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-431 | `director_engine.py` | L497 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-432 | `director_engine.py` | L541 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-433 | `director_engine.py` | L597 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-434 | `director_engine.py` | L642 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-435 | `director_engine.py` | L697 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-436 | `disk_manager.py` | L105 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-437 | `draft_manager.py` | L130 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-27 |
| TD-438 | `draft_manager.py` | L201 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-27 |
| TD-439 | `draft_manager.py` | L271 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-27 |
| TD-440 | `error_reporter.py` | L60 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-441 | `error_reporter.py` | L69 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-442 | `gemini_chunker_fixed.py` | L125 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-22 |
| TD-443 | `gemini_client_factory.py` | L75 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-22 |
| TD-444 | `gemini_semantic_chunker_deprecated.py` | L105 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-25 |
| TD-445 | `generation_engine.py` | L119 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-446 | `generation_engine.py` | L214 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-447 | `generation_engine.py` | L283 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-448 | `generation_engine.py` | L346 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-449 | `harness/evaluator_optimizer.py` | L386 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-25 |
| TD-450 | `harness/evaluator_optimizer.py` | L636 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-25 |
| TD-451 | `harness/evaluator_optimizer.py` | L647 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-25 |
| TD-452 | `harness/governance.py` | L359 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-24 |
| TD-453 | `harness/hooks.py` | L231 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-27 |
| TD-454 | `harness/hooks.py` | L437 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-27 |
| TD-455 | `harness/session_manager.py` | L171 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-08 |
| TD-456 | `harness/session_manager.py` | L331 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-08 |
| TD-457 | `hybrid_pipeline.py` | L230 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-26 |
| TD-458 | `hybrid_pipeline.py` | L295 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-26 |
| TD-459 | `interactive_preview.py` | L120 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-460 | `interactive_preview.py` | L228 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-461 | `interactive_preview.py` | L341 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-462 | `interactive_preview.py` | L385 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-463 | `learning_loop.py` | L99 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-464 | `learning_loop.py` | L108 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-465 | `learning_loop.py` | L119 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-466 | `learning_loop.py` | L295 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-467 | `list_models.py` | L29 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-07 |
| TD-468 | `live_api_handler.py` | L80 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-26 |
| TD-469 | `live_api_handler.py` | L96 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-26 |
| TD-470 | `live_api_handler.py` | L106 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-26 |
| TD-471 | `log_manager.py` | L105 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-07 |
| TD-472 | `logging_middleware.py` | L47 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-05 |
| TD-473 | `logo_manager.py` | L87 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-24 |
| TD-474 | `logo_manager.py` | L104 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-24 |
| TD-475 | `logo_manager.py` | L161 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-24 |
| TD-476 | `logo_overlay.py` | L108 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-25 |
| TD-477 | `main.py` | L84 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-27 |
| TD-478 | `main.py` | L92 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-27 |
| TD-479 | `main.py` | L104 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-27 |
| TD-480 | `main.py` | L112 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-27 |
| TD-481 | `main.py` | L123 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-27 |
| TD-482 | `main.py` | L131 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-27 |
| TD-483 | `main.py` | L273 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-27 |
| TD-484 | `mcp_server.py` | L51 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-22 |
| TD-485 | `mcp_server.py` | L103 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-22 |
| TD-486 | `phase0_preflight.py` | L77 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-21 |
| TD-487 | `phase1_full_processing.py` | L50 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-23 |
| TD-488 | `plugins/auto_chapters_plugin.py` | L99 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-27 |
| TD-489 | `plugins/lightweight_scan_plugin.py` | L60 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-27 |
| TD-490 | `plugins/opening_ending_plugin.py` | L54 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-26 |
| TD-491 | `plugins/opening_ending_plugin.py` | L62 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-26 |
| TD-492 | `plugins/opening_ending_plugin.py` | L116 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-26 |
| TD-493 | `plugins/thumbnail_plugin.py` | L108 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-494 | `plugins/youtube_optimizer_plugin.py` | L707 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-23 |
| TD-495 | `plugins/youtube_optimizer_plugin.py` | L825 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-23 |
| TD-496 | `preview_engine.py` | L53 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-497 | `preview_system.py` | L102 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-14 |
| TD-498 | `preview_system.py` | L130 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-14 |
| TD-499 | `preview_system.py` | L232 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-14 |
| TD-500 | `production_preview.py` | L126 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-23 |
| TD-501 | `progressive_preview.py` | L116 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-502 | `progressive_preview.py` | L142 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-503 | `progressive_preview.py` | L316 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-504 | `progressive_preview.py` | L450 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-505 | `progressive_preview.py` | L514 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-506 | `progressive_preview_report.py` | L30 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-26 |
| TD-507 | `proper_noun_dict.py` | L73 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-24 |
| TD-508 | `quality_gate_agent.py` | L97 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-23 |
| TD-509 | `quality_gate_ai.py` | L88 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-27 |
| TD-510 | `quality_gate_plugins.py` | L135 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-07 |
| TD-511 | `quality_gate_plugins.py` | L523 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-07 |
| TD-512 | `quality_gate_plugins.py` | L554 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-07 |
| TD-513 | `quality_gate_plugins.py` | L585 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-07 |
| TD-514 | `quality_gate_plugins.py` | L703 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-07 |
| TD-515 | `quality_gate_plugins.py` | L964 | 🔵 accepted | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-07 |
| TD-516 | `redis_config.py` | L53 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-22 |
| TD-517 | `safe_io.py` | L86 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-08 |
| TD-518 | `self_review_engine.py` | L158 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-519 | `self_review_engine.py` | L283 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-520 | `self_review_engine.py` | L322 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-521 | `semantic_store.py` | L153 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-522 | `semantic_store.py` | L281 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-523 | `service_container.py` | L70 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-524 | `service_container.py` | L194 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-525 | `services/comment_analyzer.py` | L165 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-04 |
| TD-526 | `services/embedding_service.py` | L60 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-08 |
| TD-527 | `services/embedding_service.py` | L90 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-08 |
| TD-528 | `services/hook_improver.py` | L124 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-529 | `services/hook_improver.py` | L217 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-530 | `services/hook_preview_generator.py` | L112 | 🔵 accepted | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-25 |
| TD-531 | `services/hook_preview_generator.py` | L172 | 🔵 accepted | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-25 |
| TD-532 | `services/thumbnail_analyzer.py` | L183 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-533 | `services/vector_search.py` | L86 | 🔵 accepted | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-25 |
| TD-534 | `services/vector_search.py` | L109 | 🔵 accepted | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-25 |
| TD-535 | `services/youtube_ab_test.py` | L35 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-15 |
| TD-536 | `services/youtube_ab_test.py` | L44 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-15 |
| TD-537 | `services/youtube_analytics_client.py` | L197 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-08 |
| TD-538 | `services/youtube_analytics_client.py` | L299 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-08 |
| TD-539 | `services/youtube_analytics_client.py` | L386 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-08 |
| TD-540 | `services/youtube_uploader.py` | L77 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-541 | `services/youtube_uploader.py` | L144 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-07 |
| TD-542 | `services/youtube_uploader.py` | L219 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-543 | `subtitle_confirmation.py` | L91 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-544 | `subtitle_confirmation.py` | L128 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-545 | `subtitle_engine/ai_proofreader.py` | L50 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-23 |
| TD-546 | `subtitle_engine/ai_proofreader.py` | L178 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-23 |
| TD-547 | `subtitle_engine/ai_proofreader.py` | L235 | 🔵 accepted | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-23 |
| TD-548 | `subtitle_engine/speaker_diarizer.py` | L96 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-22 |
| TD-549 | `subtitle_engine/speaker_diarizer.py` | L102 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-22 |
| TD-550 | `subtitle_engine/whisper_subprocess.py` | L194 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-27 |
| TD-551 | `subtitle_engine/whisper_subprocess.py` | L268 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-27 |
| TD-552 | `subtitle_engine/whisper_transcriber.py` | L74 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-27 |
| TD-553 | `subtitle_engine/whisper_transcriber.py` | L86 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-27 |
| TD-554 | `subtitle_engine/whisper_transcriber.py` | L112 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-27 |
| TD-555 | `subtitle_engine/whisper_transcriber.py` | L205 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-27 |
| TD-556 | `subtitle_normalizer.py` | L133 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-27 |
| TD-557 | `task_store.py` | L185 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-27 |
| TD-558 | `task_store.py` | L222 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-27 |
| TD-559 | `task_store.py` | L250 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-27 |
| TD-560 | `task_store.py` | L314 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-27 |
| TD-561 | `telop_proposal_engine.py` | L145 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-23 |
| TD-562 | `telop_proposal_engine.py` | L240 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-23 |
| TD-563 | `template_recommender.py` | L253 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-24 |
| TD-564 | `theme_telop.py` | L50 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-07 |
| TD-565 | `thumbnail_engine/generator.py` | L113 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-25 |
| TD-566 | `thumbnail_engine/generator.py` | L131 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-25 |
| TD-567 | `thumbnail_engine/generator.py` | L199 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-25 |
| TD-568 | `thumbnail_engine/generator.py` | L249 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-569 | `tight_layout_generator.py` | L163 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-08 |
| TD-570 | `topleft_clean_generator.py` | L166 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-15 |
| TD-571 | `usage_tracker/alert_system.py` | L85 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-572 | `usage_tracker/quota_manager.py` | L64 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-08 |
| TD-573 | `usage_tracker/sdk_checker.py` | L42 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-574 | `usage_tracker/sdk_checker.py` | L136 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-575 | `usage_tracker/sdk_checker.py` | L169 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-576 | `usage_tracker/tracker.py` | L69 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-27 |
| TD-577 | `usage_tracker/tracker.py` | L123 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-27 |
| TD-578 | `usage_tracker/tracker.py` | L139 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-27 |
| TD-579 | `usage_tracker/tracker.py` | L173 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-05-27 |
| TD-580 | `verified_preview_generator.py` | L199 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-581 | `video_editor_engine.py` | L110 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-582 | `video_processor.py` | L160 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-583 | `video_processor.py` | L376 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-584 | `video_processor.py` | L432 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-585 | `video_processor.py` | L450 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-586 | `video_processor.py` | L489 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-587 | `wagamama_manager.py` | L56 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-08 |
| TD-588 | `wagamama_manager.py` | L65 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-08 |
| TD-589 | `websocket_handler.py` | L202 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-27 |
| TD-590 | `websocket_handler.py` | L218 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-27 |
| TD-591 | `websocket_handler.py` | L230 | ✅ fixed | `except Exception` | ログ出力強化 / 具体的例外型に変更 | 2026-06-27 |
| TD-592 | `whisper_fixed.py` | L141 | 🔴 open | `except Exception` | ログ出力強化 / 具体的例外型に変更 | - |
| TD-600 | `services/smartcut_strategy_service.py` | L218 | ✅ fixed | `except Exception as e:` | FileNotFoundError/json.JSONDecodeError等の具体例外に分割 | 2026-06-16 |
| TD-601 | `services/smartcut_strategy_service.py` | L236 | ✅ fixed | `except Exception as e:` | FileNotFoundError/json.JSONDecodeError等の具体例外に分割 | 2026-06-16 |
| TD-602 | `services/smartcut_strategy_service.py` | L249 | ✅ fixed | `except Exception:` | FileNotFoundError/json.JSONDecodeError等の具体例外に分割 | 2026-06-08 |
| TD-603 | `services/evolution_sync_service.py` | L78 | ✅ fixed | `except Exception in sync_all: decision_logger ImportError fallback` |  | 2026-06-08 |
| TD-604 | `services/evolution_sync_service.py` | L80 | ✅ fixed | `except Exception in sync_all: decision_logger exception fallback` |  | 2026-06-08 |
| TD-605 | `services/evolution_sync_service.py` | L86 | ✅ fixed | `except Exception in sync_all: branding_manager ImportError fallback` |  | 2026-06-08 |
| TD-606 | `services/evolution_sync_service.py` | L88 | ✅ fixed | `except Exception in sync_all: branding_manager exception fallback` |  | 2026-06-08 |
| TD-607 | `services/evolution_sync_service.py` | L94 | ✅ fixed | `except Exception in sync_all: strategy count exception fallback` |  | 2026-06-08 |
| TD-608 | `services/evolution_sync_service.py` | L151 | ✅ fixed | `except Exception in record_strategy: evolution_log write exception` |  | 2026-06-08 |
| TD-624 | `services/evolution_trigger_service.py` | L314 | ✅ fixed | `UNCOVERED_BRANCH` |  | 2026-05-27 |
| TD-625 | `services/philosophy_proposal_service.py` | L388 | ✅ fixed | `UNCOVERED_BRANCH` |  | 2026-06-08 |
| TD-626 | `services/smartcut_strategy_service.py` | L216 | ✅ fixed | `UNCOVERED_BRANCH` |  | 2026-06-08 |
| TD-627 | `cleanup_manager.py` | L180 | ✅ fixed | `UNCOVERED_BRANCH` |  | 2026-06-05 |
| TD-629 | `tests/e2e/test_e2e_10_theme.py` | L1 | ✅ fixed | `xfail:50件 DS-12 theme_router未登録` |  | 2026-06-08 |
| TD-630 | `tests/e2e/test_e2e_12_soul_evolution.py` | L1 | ✅ fixed | `xfail:10件 M4.2 evolution API応答構造変更` |  | 2026-06-08 |
| TD-631 | `tests/e2e/test_e2e_04_smartcut.py` | L1 | ✅ fixed | `xfail:3件 M4.1 finalize応答フォーマット変更` |  | 2026-06-08 |
| TD-632 | `tests/e2e/test_e2e_05_adjustment.py` | L1 | ✅ fixed | `xfail:3件 M4.1 SmartCut finalize依存` |  | 2026-06-08 |
| TD-633 | `tests/e2e/test_e2e_11_preproduction.py` | L1 | ✅ fixed | `xfail:1件 M3.3 テンプレート推薦ロジック変更` |  | 2026-05-21 |
| TD-634 | `tests/test_shared/test_batch12_gen_legacy_branding.py` | L443 | ✅ fixed | `xfail:3件 Sprint4.2.1 EvolutionTriggerService委譲` |  | 2026-06-08 |
| TD-635 | `tests/test_shared/test_batch8_pipeline_asset_director.py` | L135 | ✅ fixed | `xfail:1件 Sprint4.3.2 _record_force_render変更` |  | 2026-06-08 |
| TD-636 | `tests/test_shared/test_branding_manager.py` | L144 | ✅ fixed | `xfail:2件 Sprint4.2.1 EvolutionTriggerService委譲` |  | 2026-06-08 |
| TD-637 | `main.py` | L0 | ✅ fixed | `uncovered_branch` |  | 2026-06-08 |
| TD-638 | `routers/websocket.py` | L0 | ✅ fixed | `uncovered_branch` |  | 2026-05-23 |
| TD-639 | `director_engine.py` | L0 | ✅ fixed | `uncovered_branch` |  | 2026-06-08 |
| TD-642 | `services/performance_budget_manager.py` | L200 | ✅ fixed | `unbounded file accumulation` |  | 2026-06-08 |
| TD-643 | `services/performance_budget_manager.py` | L30 | ✅ fixed | `dual source of truth (DEFAULT dict + JSON file)` |  | 2026-06-08 |
| TD-644 | `routers/admin_setup_router.py` | L622 | ✅ fixed | `hardcoded worker names` |  | 2026-06-08 |
| TD-645 | `routers/websocket.py` | L66 | 🔵 accepted | `DP-06` |  | 2026-06-12 |
| TD-646 | `routers/websocket.py` | L1 | ✅ fixed | `DP-06` |  | 2026-05-23 |
| TD-647 | `routers/legacy_production_router.py` | L1 | ✅ fixed | `DP-06` |  | 2026-06-08 |
| TD-648 | `usage_tracker/tracker.py` | L1 | ✅ fixed | `DP-06` |  | 2026-06-08 |
| TD-649 | `logo_overlay.py` | L1 | ✅ fixed | `DP-06` |  | 2026-05-25 |
| TD-654 | `generate_full_inspection.py` | L26 | ✅ fixed | `except Exception as e:` |  | 2026-06-08 |
| TD-655 | `generate_full_inspection.py` | L39 | ✅ fixed | `except Exception:` |  | 2026-06-08 |
| TD-656 | `generate_full_inspection.py` | L52 | ✅ fixed | `except Exception:` |  | 2026-06-08 |
| TD-657 | `metadata_generator.py` | L145 | ✅ fixed | `except Exception:` |  | 2026-05-22 |
| TD-658 | `run_self_improvement_loop.py` | L153 | 🔴 open | `except Exception:` |  | - |
| TD-659 | `self_improvement_engine.py` | L184 | ✅ fixed | `except Exception as e:` |  | 2026-06-07 |
| TD-660 | `self_improvement_engine.py` | L603 | ✅ fixed | `except Exception as e:` |  | 2026-06-07 |
| TD-661 | `graded_previews/youtuber_grade_scorer.py` | L80 | 🔵 accepted | `except Exception as e:` | 具体例外キャッチ | 2026-05-28 |
| TD-662 | `graded_previews/youtuber_grade_scorer.py` | L121 | 🔵 accepted | `except Exception:` | 具体例外キャッチ | 2026-05-28 |
| TD-663 | `agents/orchestration/orchestrator.py` | L77 | ✅ fixed | `except Exception:` | 特定の例外捕捉にリファクタリングする、または明示的なロギングを追加する | 2026-06-08 |
| TD-664 | `agents/orchestration/orchestrator.py` | L305 | ✅ fixed | `except Exception:` | 特定の例外捕捉にリファクタリングする、または明示的なロギングを追加する | 2026-06-08 |
| TD-665 | `agents/orchestration/orchestrator.py` | L475 | ✅ fixed | `except Exception:` | 特定の例外捕捉にリファクタリングする、または明示的なロギングを追加する | 2026-06-08 |
| TD-666 | `agents/orchestration/orchestrator.py` | L485 | ✅ fixed | `except Exception:` | 特定の例外捕捉にリファクタリングする、または明示的なロギングを追加する | 2026-06-08 |
| TD-667 | `agents/orchestration/orchestrator.py` | L1215 | 🔴 open | `except Exception as e:` | 特定の例外捕捉にリファクタリングする、または明示的なロギングを追加する | - |
| TD-668 | `agents/orchestration/orchestrator.py` | L1234 | ✅ fixed | `except Exception:` | 特定の例外捕捉にリファクタリングする、または明示的なロギングを追加する | 2026-06-08 |
| TD-669 | `agents/orchestration/orchestrator.py` | L1365 | ✅ fixed | `except Exception:` | 特定の例外捕捉にリファクタリングする、または明示的なロギングを追加する | 2026-06-08 |
| TD-670 | `tests/e2e/test_e2e_m36_o11_preproduction_lab.py` | L293 | ✅ fixed | `xfail:1件 M3.3 テンプレート推薦ロジック変更` |  | 2026-06-08 |
| TD-709 | `video_processor.py` | L330 | ✅ fixed | `while process.poll() is None:` | ffmpeg進捗スレッドのテストモック化、または進捗解析ロジックの分離 | 2026-06-08 |
| TD-710 | `agents/orchestration/generate_subagent_reports.py` | L42 | 🔴 open | `except Exception:` | 特定の例外を捕捉するかログを出力する | - |
| TD-712 | `agents/stage_bound_agent.py` | L94 | 🔴 open | `except Exception as e:` | エラーハンドリングの具現化 | - |
| TD-714 | `model_governance_local.py` | L171 | ✅ fixed | `except Exception as e:` | エラーハンドリングの具現化 | 2026-06-06 |
| TD-715 | `agents/workers/transcribe_worker.py` | L76 | ✅ fixed | `except Exception as e:` |  | 2026-05-24 |
| TD-733 | `../../../AppData/Local/Temp/pytest-of-PC_User/pytest-1572/test_wagamama_ledger_loading_b0/Human01_Official Artifact/サブエージェント体制報告/定時レポート/phase_5_completion_20260523.md` | L1 | 🔵 accepted | `AUTOMATED_ALERT: QUALITY_DROP` | システム安定性の確認と品質/リソースの適正化 | 2026-05-23 |
| TD-734 | `../../../AppData/Local/Temp/pytest-of-PC_User/pytest-1572/test_wagamama_ledger_loading_b0/Human01_Official Artifact/サブエージェント体制報告/定時レポート/phase_6_completion_20260523.md` | L1 | 🔵 accepted | `AUTOMATED_ALERT: QUALITY_DROP` | システム安定性の確認と品質/リソースの適正化 | 2026-05-23 |
| TD-735 | `../../../AppData/Local/Temp/pytest-of-PC_User/pytest-1572/test_generate_phase_report_pha0/Human01_Official Artifact/サブエージェント体制報告/定時レポート/phase_7_completion_20260523.md` | L1 | 🔵 accepted | `AUTOMATED_ALERT: QUALITY_DROP` | システム安定性の確認と品質/リソースの適正化 | 2026-05-23 |
| TD-736 | `../../../AppData/Local/Temp/pytest-of-PC_User/pytest-1572/test_generate_phase_report_pha0/Human01_Official Artifact/サブエージェント体制報告/定時レポート/phase_8_completion_20260523.md` | L1 | 🔵 accepted | `AUTOMATED_ALERT: QUALITY_DROP` | システム安定性の確認と品質/リソースの適正化 | 2026-05-23 |
| TD-737 | `../../../AppData/Local/Temp/pytest-of-PC_User/pytest-1572/test_generate_phase_report_pha1/Human01_Official Artifact/サブエージェント体制報告/定時レポート/phase_19_completion_20260523.md` | L1 | 🔵 accepted | `AUTOMATED_ALERT: QUALITY_DROP` | システム安定性の確認と品質/リソースの適正化 | 2026-05-23 |
| TD-738 | `../../../AppData/Local/Temp/pytest-of-PC_User/pytest-1572/test_generate_phase_report_pha1/Human01_Official Artifact/サブエージェント体制報告/定時レポート/phase_20_completion_20260523.md` | L1 | 🔵 accepted | `AUTOMATED_ALERT: QUALITY_DROP` | システム安定性の確認と品質/リソースの適正化 | 2026-05-23 |
| TD-739 | `services/tdr_resolver.py` | L122 | 🔴 open | `except Exception as store_err:` | except Exception as store_err: logger.error...; raise | - |
| TD-742 | `agents/orchestration/atomic_io.py` | L61 | ✅ fixed | `except Exception:` | 具体的な例外に分割する | 2026-05-30 |
| TD-743 | `agents/orchestration/health_check.py` | L128 | 🔴 open | `except Exception as e:` | 具体的な例外に分割する | - |
| TD-744 | `agents/orchestration/health_check.py` | L164 | 🔴 open | `except Exception:` | 具体的な例外に分割する | - |
| TD-745 | `agents/orchestration/health_check.py` | L385 | 🔴 open | `except Exception as e:` | 具体的な例外に分割する | - |
| TD-746 | `inspect_latest.py` | L35 | ✅ fixed | `except Exception as e:` | 具体的な例外に分割する | 2026-06-27 |
| TD-747 | `inspect_latest.py` | L63 | ✅ fixed | `except Exception as e:` | 具体的な例外に分割する | 2026-06-27 |
| TD-749 | `agents/orchestration/improvement_analyzer.py` | L350 | ✅ fixed | `except Exception:` | except Exception as e への変更や適切なエラーキャッチ | 2026-06-28 |
| TD-795 | `agents/graph.py` | L49 | 🔵 accepted | `except Exception (broad catch)` | 具体的例外クラスに限定 | 2026-05-29 |
| TD-796 | `agents/graph.py` | L57 | 🔵 accepted | `except Exception (broad catch)` | 具体的例外クラスに限定 | 2026-06-12 |
| TD-797 | `agents/graph.py` | L63 | 🔵 accepted | `except Exception (broad catch)` | 具体的例外クラスに限定 | 2026-06-12 |
| TD-799 | `design_alternatives.py` | L48 | 🔴 open | `except Exception as e:` | 具体的な例外の個別キャッチ | - |
| TD-800 | `design_alternatives.py` | L78 | 🔴 open | `except Exception as e:` | 具体的な例外の個別キャッチ | - |
| TD-801 | `design_alternatives.py` | L99 | 🔴 open | `except Exception as e:` | 具体的な例外の個別キャッチ | - |
| TD-802 | `design_alternatives.py` | L113 | 🔴 open | `except Exception as e:` | 具体的な例外の個別キャッチ | - |
| TD-803 | `design_alternatives.py` | L130 | 🔴 open | `except Exception as e:` | 具体的な例外の個別キャッチ | - |
| TD-804 | `design_alternatives.py` | L150 | 🔴 open | `except Exception as e:` | 具体的な例外の個別キャッチ | - |
| TD-805 | `design_alternatives.py` | L160 | 🔴 open | `except Exception as e:` | 具体的な例外の個別キャッチ | - |
| TD-806 | `design_alternatives.py` | L176 | 🔴 open | `except Exception as e:` | 具体的な例外の個別キャッチ | - |
| TD-807 | `design_alternatives.py` | L183 | 🔴 open | `except Exception as e:` | 具体的な例外の個別キャッチ | - |
| TD-808 | `design_alternatives.py` | L199 | 🔴 open | `except Exception as debt_err:` | 具体的な例外の個別キャッチ | - |
| TD-809 | `design_alternatives.py` | L209 | 🔴 open | `except Exception as e:` | 具体的な例外の個別キャッチ | - |
| TD-822 | `agents/task_contract.py` | L365 | ✅ fixed | `except OSError as e:` | file exists check security fallback | 2026-06-23 |
| TD-851 | `agents/orchestration/get_system_status.py` | L128 | 🔵 accepted | `except Exception:` |  | 2026-06-07 |
| TD-852 | `gcp_cost_monitor.py` | L160 | 🔴 open | `except Exception as e:` |  | - |
| TD-853 | `gcp_cost_monitor.py` | L164 | 🔴 open | `except Exception:` |  | - |
| TD-854 | `gcp_cost_monitor.py` | L186 | 🔴 open | `except Exception as e:` |  | - |
| TD-855 | `gcp_cost_monitor.py` | L194 | 🔴 open | `except Exception as e:` |  | - |
| TD-857 | `services/series_planner.py` | L201 | 🔴 open | `except Exception as e:` | 具体的な例外の個別キャッチ | - |
| TD-858 | `services/series_planner.py` | L205 | 🔴 open | `except Exception:` | 具体的な例外の個別キャッチ | - |
| TD-859 | `services/series_planner.py` | L225 | 🔴 open | `except Exception as e:` | 具体的な例外の個別キャッチ | - |
| TD-860 | `services/series_planner.py` | L232 | 🔴 open | `except Exception as e:` | 具体的な例外の個別キャッチ | - |
| TD-866 | `agents/orchestration/mark_task_helper.py` | L21 | ✅ fixed | `except Exception as e:` | 具体的例外への修正 | 2026-06-14 |
| TD-877 | `agents/orchestration/harness_auditor.py` | L41 | ✅ fixed | `except Exception` | エラーハンドリングの共通化 | 2026-06-11 |
| TD-878 | `agents/orchestration/harness_auditor.py` | L60 | ✅ fixed | `except Exception` | エラーハンドリングの共通化 | 2026-06-11 |
| TD-879 | `agents/orchestration/harness_auditor.py` | L72 | ✅ fixed | `except Exception` | エラーハンドリングの共通化 | 2026-06-11 |
| TD-880 | `agents/orchestration/harness_auditor.py` | L81 | ✅ fixed | `except Exception` | エラーハンドリングの共通化 | 2026-06-11 |
| TD-881 | `agents/orchestration/harness_auditor.py` | L94 | ✅ fixed | `except Exception` | エラーハンドリングの共通化 | 2026-06-11 |
| TD-882 | `agents/orchestration/harness_auditor.py` | L124 | ✅ fixed | `except Exception` | エラーハンドリングの共通化 | 2026-06-11 |
| TD-883 | `agents/orchestration/harness_auditor.py` | L158 | ✅ fixed | `except Exception` | エラーハンドリングの共通化 | 2026-06-11 |
| TD-884 | `agents/orchestration/harness_auditor.py` | L166 | ✅ fixed | `except Exception` | エラーハンドリングの共通化 | 2026-06-11 |
| TD-885 | `agents/orchestration/harness_auditor.py` | L203 | ✅ fixed | `except Exception` | エラーハンドリングの共通化 | 2026-06-11 |
| TD-886 | `agents/orchestration/harness_auditor.py` | L223 | ✅ fixed | `except Exception` | エラーハンドリングの共通化 | 2026-06-11 |
| TD-887 | `agents/orchestration/harness_auditor.py` | L245 | ✅ fixed | `except Exception` | エラーハンドリングの共通化 | 2026-06-11 |
| TD-888 | `agents/orchestration/harness_auditor.py` | L264 | ✅ fixed | `except Exception` | エラーハンドリングの共通化 | 2026-06-11 |
| TD-920 | `agents/orchestration/get_batch_details.py` | L22 | ✅ fixed | `except Exception as e:` | 本スクリプトのエラー安全処理として例外をキャッチして終了コード1で終了する | 2026-06-15 |
| TD-923 | `agents/orchestration/flash_runner_next_batch.py` | L30 | ✅ fixed | `except Exception as e:` | エラーのログ出力とプロセスの終了 | 2026-06-03 |
| TD-929 | `phase_a_telops_srt.py` | L124 | ✅ fixed | `except Exception as e:` | Logged and returned None | 2026-06-23 |
| TD-930 | `phase_a_telops_srt.py` | L137 | ✅ fixed | `except Exception as tdr_err:` | Fallback print statement on TDR failure | 2026-06-23 |
| TD-932 | `agents/orchestration/memory_distiller.py` | L46 | ✅ fixed | `except Exception as e:` | ログ出力のみのため、MINOR_INFRAとして登録 | 2026-06-27 |
| TD-933 | `agents/orchestration/memory_distiller.py` | L133 | ✅ fixed | `except Exception as e:` | 例外ログ出力のみのため、MINOR_INFRAとして登録 | 2026-06-27 |
| TD-934 | `agents/vector_utils.py` | L18 | ✅ fixed | `except Exception as e:` | エラーハンドリングして空リストを返す。ログ主力あり。 | 2026-06-08 |
| TD-952 | `branding/analytics_manager.py` | L155 | ✅ fixed | `except Exception as e:` | Pillow/Image関連の具体的な例外（OSErrorなど）に修正する | 2026-06-27 |
| TD-953 | `branding/analytics_manager.py` | L178 | ✅ fixed | `except Exception as e:` | Pillow/Image関連の具体的な例外に修正する | 2026-06-27 |
| TD-954 | `routers/error_schemas.py` | L100 | ✅ fixed | `except Exception as e:` | 安全なRequest-ID取得のための例外キャッチ。ログ出力あり。 | 2026-06-08 |
| TD-955 | `routers/error_schemas.py` | L115 | ✅ fixed | `except Exception as e:` | global_exception_handler内でのRequest-ID抽出例外キャッチ。ログ出力あり。 | 2026-06-08 |
| TD-956 | `routers/error_schemas.py` | L143 | ✅ fixed | `except Exception as e:` | http_exception_handler内でのRequest-ID抽出例外キャッチ。ログ出力あり。 | 2026-06-08 |
| TD-957 | `subtitle_engine/ai_proofreader.py` | L240 | 🔴 open | `except Exception as e:` | API呼び出しの接続エラー・クォータエラー処理のための例外キャッチ。ログ出力またはリトライ判定あり。 | - |
| TD-958 | `subtitle_engine/ai_proofreader.py` | L334 | 🔴 open | `except Exception as e:` | API呼び出しの接続エラー・クォータエラー処理のための例外キャッチ。ログ出力またはリトライ判定あり。 | - |
| TD-959 | `services/thumbnail_analyzer.py` | L212 | 🔴 open | `except Exception as e:` | Pillowによる画像保存やアスペクト比計算時などの例外キャッチ。ログ出力あり。 | - |
| TD-960 | `services/thumbnail_analyzer.py` | L613 | 🔴 open | `except Exception as e:` | Pillowによる画像保存やアスペクト比計算時などの例外キャッチ。ログ出力あり。 | - |
| TD-961 | `services/thumbnail_analyzer.py` | L625 | 🔴 open | `except Exception:` | Pillowによる画像保存やアスペクト比計算時などの例外キャッチ。ログ出力あり。 | - |
| TD-962 | `services/thumbnail_analyzer.py` | L658 | 🔴 open | `except Exception as e:` | Pillowによる画像保存やアスペクト比計算時などの例外キャッチ。ログ出力あり。 | - |
| TD-963 | `services/thumbnail_analyzer.py` | L668 | 🔴 open | `except Exception as e:` | Pillowによる画像保存やアスペクト比計算時などの例外キャッチ。ログ出力あり。 | - |
| TD-964 | `services/thumbnail_analyzer.py` | L711 | 🔴 open | `except Exception as e:` | Pillowによる画像保存やアスペクト比計算時などの例外キャッチ。ログ出力あり。 | - |
| TD-965 | `verified_preview_generator.py` | L54 | 🔴 open | `except Exception as e:` | Pillowによる画像生成・リサイズなどの例外キャッチ。ログ出力あり。 | - |
| TD-966 | `verified_preview_generator.py` | L245 | ✅ fixed | `except Exception as fe_draw:` | Pillowによる画像生成・リサイズなどの例外キャッチ。ログ出力あり。 | 2026-06-27 |
| TD-967 | `verified_preview_generator.py` | L269 | 🔴 open | `except Exception as e:` | Pillowによる画像生成・リサイズなどの例外キャッチ。ログ出力あり。 | - |
| TD-968 | `verified_preview_generator.py` | L535 | 🔴 open | `except Exception as e:` | Pillowによる画像生成・リサイズなどの例外キャッチ。ログ出力あり。 | - |
| TD-969 | `verified_preview_generator.py` | L695 | 🔴 open | `except Exception as e:` | Pillowによる画像生成・リサイズなどの例外キャッチ。ログ出力あり。 | - |
| TD-970 | `verified_preview_generator.py` | L724 | 🔴 open | `except Exception as ve:` | Pillowによる画像生成・リサイズなどの例外キャッチ。ログ出力あり。 | - |
| TD-971 | `verified_preview_generator.py` | L741 | 🔴 open | `except Exception as e:` | Pillowによる画像生成・リサイズなどの例外キャッチ。ログ出力あり。 | - |
| TD-972 | `services/smartcut_strategy_service.py` | L235 | ✅ fixed | `except Exception as e:` | 例外のログ記録、またはブランドスコアパース例外時のフォールバック処理。 | 2026-06-23 |
| TD-973 | `routers/trinity.py` | L43 | 🔴 open | `except Exception as e:` | 例外のログ記録、またはTDR自動登録時の例外キャッチ。 | - |
| TD-974 | `routers/trinity.py` | L59 | 🔴 open | `except Exception as e:` | 例外のログ記録、またはTDR自動登録時の例外キャッチ。 | - |
| TD-975 | `routers/trinity.py` | L60 | ✅ fixed | `_register_router_debt(44, "except Exception as e:", str(e), "get_trinity_status")` | 例外のログ記録、またはTDR自動登録時の例外キャッチ。 | 2026-06-27 |
| TD-976 | `routers/trinity.py` | L75 | 🔴 open | `except Exception as e:` | 例外のログ記録、またはTDR自動登録時の例外キャッチ。 | - |
| TD-977 | `routers/trinity.py` | L76 | 🔴 open | `_register_router_debt(60, "except Exception as e:", str(e), "sync_analytics")` | 例外のログ記録、またはTDR自動登録時の例外キャッチ。 | - |
| TD-978 | `routers/trinity.py` | L99 | 🔴 open | `except Exception as e:` | 例外のログ記録、またはTDR自動登録時の例外キャッチ。 | - |
| TD-979 | `routers/trinity.py` | L100 | 🔴 open | `_register_router_debt(84, "except Exception as e:", str(e), "simulate_analytics")` | 例外のログ記録、またはTDR自動登録時の例外キャッチ。 | - |
| TD-980 | `routers/trinity.py` | L115 | 🔴 open | `except Exception as e:` | 例外のログ記録、またはTDR自動登録時の例外キャッチ。 | - |
| TD-981 | `routers/trinity.py` | L116 | 🔴 open | `_register_router_debt(100, "except Exception as e:", str(e), "get_models")` | 例外のログ記録、またはTDR自動登録時の例外キャッチ。 | - |
| TD-982 | `routers/trinity.py` | L131 | 🔴 open | `except Exception as e:` | 例外のログ記録、またはTDR自動登録時の例外キャッチ。 | - |
| TD-983 | `routers/trinity.py` | L132 | 🔴 open | `_register_router_debt(116, "except Exception as e:", str(e), "get_evolution")` | 例外のログ記録、またはTDR自動登録時の例外キャッチ。 | - |
| TD-984 | `routers/trinity.py` | L153 | 🔴 open | `except Exception as e:` | 例外のログ記録、またはTDR自動登録時の例外キャッチ。 | - |
| TD-985 | `routers/trinity.py` | L154 | 🔴 open | `_register_router_debt(138, "except Exception as e:", str(e), "sync_evolution")` | 例外のログ記録、またはTDR自動登録時の例外キャッチ。 | - |
| TD-986 | `routers/trinity.py` | L173 | 🔴 open | `except Exception as e:` | 例外のログ記録、またはTDR自動登録時の例外キャッチ。 | - |
| TD-987 | `routers/trinity.py` | L174 | 🔴 open | `_register_router_debt(158, "except Exception as e:", str(e), "get_evolution_status")` | 例外のログ記録、またはTDR自動登録時の例外キャッチ。 | - |
| TD-988 | `routers/trinity.py` | L208 | 🔴 open | `except Exception as e:` | 例外のログ記録、またはTDR自動登録時の例外キャッチ。 | - |
| TD-989 | `routers/trinity.py` | L209 | 🔴 open | `_register_router_debt(193, "except Exception as e:", str(e), "get_evolution_proposals")` | 例外のログ記録、またはTDR自動登録時の例外キャッチ。 | - |
| TD-990 | `routers/trinity.py` | L231 | 🔴 open | `except Exception as e:` | 例外のログ記録、またはTDR自動登録時の例外キャッチ。 | - |
| TD-991 | `routers/trinity.py` | L232 | 🔴 open | `_register_router_debt(216, "except Exception as e:", str(e), "approve_evolution_proposal")` | 例外のログ記録、またはTDR自動登録時の例外キャッチ。 | - |
| TD-992 | `routers/trinity.py` | L254 | 🔴 open | `except Exception as e:` | 例外のログ記録、またはTDR自動登録時の例外キャッチ。 | - |
| TD-993 | `routers/trinity.py` | L255 | 🔴 open | `_register_router_debt(239, "except Exception as e:", str(e), "reject_evolution_proposal")` | 例外のログ記録、またはTDR自動登録時の例外キャッチ。 | - |
| TD-994 | `routers/trinity.py` | L280 | 🔴 open | `except Exception as e:` | 例外のログ記録、またはTDR自動登録時の例外キャッチ。 | - |
| TD-995 | `routers/trinity.py` | L281 | 🔴 open | `_register_router_debt(265, "except Exception as e:", str(e), "get_evolution_dashboard")` | 例外のログ記録、またはTDR自動登録時の例外キャッチ。 | - |
| TD-996 | `routers/trinity.py` | L305 | 🔴 open | `except Exception as e:` | 例外のログ記録、またはTDR自動登録時の例外キャッチ。 | - |
| TD-997 | `routers/trinity.py` | L306 | 🔴 open | `_register_router_debt(290, "except Exception as e:", str(e), "get_evolution_triggers")` | 例外のログ記録、またはTDR自動登録時の例外キャッチ。 | - |
| TD-998 | `main.py` | L96 | ✅ fixed | `except Exception as e:` | 例外のログ記録、またはTDR自動登録時の例外キャッチ。 | 2026-06-27 |
| TD-999 | `main.py` | L116 | ✅ fixed | `except Exception as e:` | 例外のログ記録、またはTDR自動登録時の例外キャッチ。 | 2026-06-27 |

---

## ACCEPTED_SAFETY: 正当な安全ネット（修正不要） (152件 / open:57 fixed:55)

| ID | ファイル | 行 | ステータス | パターン | 修正パターン | 修正日 |
|:--|:---|:---:|:---:|:---|:---|:---|
| TD-1049 | `plugins/report_generator_plugin.py` | L44 | ✅ fixed | `except Exception as e:` | 本番環境でのレポート生成・書込時の予期せぬ例外からパイプラインを守るための例外安全ネット | 2026-06-11 |
| TD-1052 | `settings_manager.py` | L84 | 🔴 open | `except Exception as e:` | No fix needed. General exception handler captures unexpected issues and logs them before returning an error dict to the frontend. | - |
| TD-1053 | `settings_manager.py` | L97 | 🔴 open | `except Exception as e:` | No fix needed. General exception handler captures unexpected issues and logs them before returning an error dict to the frontend. | - |
| TD-1054 | `settings_manager.py` | L125 | 🔴 open | `except Exception as e:` | No fix needed. General exception handler captures unexpected issues and logs them before returning an error dict to the frontend. | - |
| TD-1066 | `routers/websocket.py` | L191 | 🔴 open | `except Exception as close_err:` | No fix needed. This is a safety net for close calls on already closed websockets. | - |
| TD-1068 | `agents/workers/transcribe_worker.py` | L127 | 🔴 open | `except Exception:` | パイプクローズ時の安全ネット（現状維持で許容） | - |
| TD-1197 | `cleanup_manager.py` | L406 | ✅ fixed | `except Exception as e:` | 安全ネット。補助的サービスの初期化失敗からメインのクリーンアップ処理を守るための妥当な広範例外捕捉 | 2026-06-07 |
| TD-1198 | `cleanup_manager.py` | L420 | ✅ fixed | `except Exception as e:` | 安全ネット。信頼度履歴のトリミング処理の失敗からメインのクリーンアップ処理を守るための妥当な広範例外捕捉 | 2026-06-07 |
| TD-1199 | `cleanup_manager.py` | L428 | ✅ fixed | `except Exception as e:` | 安全ネット。提案サービスの初期化失敗からメインのクリーンアップ処理を守るための妥当な広範例外捕捉 | 2026-06-07 |
| TD-1200 | `cleanup_manager.py` | L440 | ✅ fixed | `except Exception as e:` | 安全ネット。保留提案のトリミング処理の失敗からメインのクリーンアップ処理を守るための妥当な広範例外捕捉 | 2026-06-07 |
| TD-1201 | `cleanup_manager.py` | L509 | ✅ fixed | `except Exception as e:` | 安全ネット。進化ログファイルへの書き込み/シリアライズエラーからメインのクリーンアップ処理を守るための妥当な広範例外捕捉 | 2026-06-07 |
| TD-1202 | `cleanup_manager.py` | L410 | ✅ fixed | `except Exception as e:` | No action needed (accepted safety net) | 2026-06-07 |
| TD-1203 | `cleanup_manager.py` | L424 | ✅ fixed | `except Exception as e:` | No action needed (accepted safety net) | 2026-06-07 |
| TD-1204 | `cleanup_manager.py` | L444 | ✅ fixed | `except Exception as e:` | No action needed (accepted safety net) | 2026-06-07 |
| TD-1205 | `cleanup_manager.py` | L516 | ✅ fixed | `except Exception as e:` | No action needed (accepted safety net) | 2026-06-07 |
| TD-1209 | `agents/orchestration/flash_assign_subagents_17.py` | L160 | 🔵 accepted | `except Exception as e:` | 最上位メインルーチンでの安全ネットのため修正不要。 | 2026-06-07 |
| TD-1212 | `agents/orchestration/verifier.py` | L164 | 🔵 accepted | `except Exception as e:` | Legitimate outer safety guard to prevent unexpected exceptions from crashing the retry runner. | 2026-06-07 |
| TD-1213 | `agents/orchestration/verifier.py` | L225 | 🔵 accepted | `except Exception as e:` | Legitimate outer safety guard to prevent unexpected exceptions from crashing the retry runner. | 2026-06-07 |
| TD-1214 | `cleanup_manager.py` | L413 | 🔴 open | `except (AttributeError, RuntimeError, ImportError, KeyError, NameError, Exception) as e:` |  | - |
| TD-1215 | `cleanup_manager.py` | L429 | 🔴 open | `except (AttributeError, RuntimeError, KeyError, IndexError, Exception) as e:` |  | - |
| TD-1216 | `cleanup_manager.py` | L441 | 🔴 open | `except (AttributeError, RuntimeError, ImportError, KeyError, NameError, Exception) as e:` |  | - |
| TD-1217 | `cleanup_manager.py` | L455 | 🔴 open | `except (AttributeError, RuntimeError, KeyError, IndexError, Exception) as e:` |  | - |
| TD-1218 | `services/quality_feedback_trigger.py` | L137 | 🔴 open | `except Exception as e:` |  | - |
| TD-1219 | `services/quality_feedback_trigger.py` | L291 | 🔴 open | `except Exception as e:` |  | - |
| TD-1222 | `routers/smartcut.py` | L97 | 🔴 open | `except Exception as close_err:` | 修正不要（conn.close()のエラーは安全にログ出力し無視） | - |
| TD-1223 | `agents/advisor_gate.py` | L195 | 🔵 accepted | `except Exception as e:` | なし (正当な安全ネット) | 2026-06-07 |
| TD-1224 | `agents/advisor_gate.py` | L286 | 🔵 accepted | `except Exception as e:` | なし (正当な安全ネット) | 2026-06-07 |
| TD-1228 | `scratch/get_status.py` | L18 | 🔵 accepted | `except Exception as e:` | None | 2026-06-07 |
| TD-1231 | `agents/orchestration/heartbeat_only.py` | L49 | ✅ fixed | `except Exception as e:` |  | 2026-06-23 |
| TD-1232 | `agents/orchestration/flash_runner_step.py` | L40 | 🔵 accepted | `except Exception as e:` |  | 2026-06-07 |
| TD-1247 | `antigravity_pipeline.py` | L390 | 🔵 accepted | `except Exception as e_trigger:` |  | 2026-06-10 |
| TD-1248 | `antigravity_pipeline.py` | L397 | 🔵 accepted | `except Exception as e_quality:` |  | 2026-06-10 |
| TD-1249 | `antigravity_pipeline.py` | L458 | 🔵 accepted | `except Exception as e:` |  | 2026-06-10 |
| TD-1250 | `antigravity_pipeline.py` | L471 | 🔵 accepted | `except Exception as e:` |  | 2026-06-10 |
| TD-1251 | `antigravity_pipeline.py` | L483 | 🔵 accepted | `except Exception as e:` |  | 2026-06-10 |
| TD-1252 | `services/post_publish_collector.py` | L126 | ✅ fixed | `except Exception as e:` | No action needed (accepted safety net) | 2026-06-10 |
| TD-1255 | `services/embedding_service.py` | L137 | 🔵 accepted | `except Exception as e:` | 修正不要（サービス全体の安全ネット） | 2026-06-10 |
| TD-1256 | `plugins/auto_chapters_plugin.py` | L76 | 🔴 open | `except Exception as e:` | 修正不要（プラグイン内の安全ネット） | - |
| TD-1257 | `plugins/auto_chapters_plugin.py` | L164 | ✅ fixed | `except Exception as e:` | 修正不要（プラグイン全体の安全ネット） | 2026-06-10 |
| TD-1262 | `services/post_publish_collector.py` | L139 | 🔵 accepted | `except Exception as e:` | No action needed (accepted safety net) | 2026-06-10 |
| TD-1263 | `agents/council_graph.py` | L289 | ✅ fixed | `except Exception as e:` |  | 2026-06-11 |
| TD-1264 | `agents/council_graph.py` | L247 | 🔵 accepted | `except Exception as e:` |  | 2026-06-11 |
| TD-1265 | `add_scene04_telop.py` | L69 | 🔵 accepted | `except Exception as e:` | 安全なフォールバック (None返却) | 2026-06-10 |
| TD-1267 | `add_scene04_telop.py` | L176 | 🔵 accepted | `except Exception as e:` | 安全なフォールバック (unknown秒数設定) | 2026-06-10 |
| TD-1268 | `add_scene04_telop.py` | L193 | 🔵 accepted | `except Exception as e:` | 安全なフォールバック (None返却) | 2026-06-10 |
| TD-1269 | `add_scene04_telop.py` | L206 | 🔵 accepted | `except Exception as e:` | 安全なフォールバック (削除失敗を無視して動画パスを返却) | 2026-06-10 |
| TD-1270 | `plugins/auto_chapters_plugin.py` | L30 | 🔵 accepted | `except Exception as e:` | None (Accepted Safety) | 2026-06-10 |
| TD-1271 | `plugins/auto_chapters_plugin.py` | L111 | 🔵 accepted | `except Exception as e:` | None (Accepted Safety) | 2026-06-10 |
| TD-1272 | `plugins/auto_chapters_plugin.py` | L231 | 🔵 accepted | `except Exception as e:` | None (Accepted Safety) | 2026-06-10 |
| TD-1273 | `plugins/auto_chapters_plugin.py` | L90 | 🔴 open | `except Exception as e:` | None (Accepted Safety) | - |
| TD-1274 | `services/post_publish_collector.py` | L191 | 🔴 open | `except Exception as e:` | Not needed - accepted safety net | - |
| TD-1289 | `agents/council_graph.py` | L343 | 🔵 accepted | `except Exception as e:` | except Exception: raise RuntimeError にラップ | 2026-06-11 |
| TD-1303 | `agents/orchestration/wave_scheduler.py` | L70 | ✅ fixed | `except Exception as e:` | None | 2026-06-12 |
| TD-1304 | `agents/orchestration/wave_scheduler.py` | L103 | ✅ fixed | `except Exception as e:` | None | 2026-06-12 |
| TD-1341 | `agents/orchestration/run_session_end.py` | L286 | 🔵 accepted | `except Exception as e:` | No fix required (Accepted safety net for robust session end reporting) | 2026-06-13 |
| TD-1342 | `agents/orchestration/run_session_end.py` | L350 | 🔵 accepted | `except Exception as e:` | No fix required (Accepted safety net for robust session end reporting) | 2026-06-13 |
| TD-1343 | `agents/orchestration/run_session_end.py` | L378 | 🔵 accepted | `except Exception as e:` | No fix required (Accepted safety net for robust session end reporting) | 2026-06-13 |
| TD-1344 | `agents/orchestration/run_session_end.py` | L403 | 🔵 accepted | `except Exception as e:` | No fix required (Accepted safety net for robust session end reporting) | 2026-06-13 |
| TD-1345 | `agents/orchestration/run_session_end.py` | L421 | 🔵 accepted | `except Exception as report_err:` | No fix required (Accepted safety net for robust session end reporting) | 2026-06-13 |
| TD-1346 | `agents/orchestration/learning_integration.py` | L87 | 🔴 open | `except Exception as e:` | Keep safe exception guard for orchestration stability | - |
| TD-1347 | `agents/orchestration/learning_integration.py` | L123 | 🔴 open | `except Exception as e:` | Keep safe exception guard for orchestration stability | - |
| TD-1348 | `agents/orchestration/learning_integration.py` | L265 | ✅ fixed | `except Exception as e:` | Keep safe exception guard for orchestration stability | 2026-06-13 |
| TD-1349 | `agents/orchestration/learning_integration.py` | L75 | ✅ fixed | `except Exception as e:` | Keep safe exception guard for orchestration stability | 2026-06-13 |
| TD-1350 | `agents/orchestration/learning_integration.py` | L99 | ✅ fixed | `except Exception as e:` | Keep safe exception guard for orchestration stability | 2026-06-13 |
| TD-1351 | `agents/orchestration/learning_integration.py` | L119 | ✅ fixed | `except Exception as e:` | Keep safe exception guard for orchestration stability | 2026-06-13 |
| TD-1352 | `agents/orchestration/learning_integration.py` | L138 | ✅ fixed | `except Exception as e:` | Keep safe exception guard for orchestration stability | 2026-06-13 |
| TD-1395 | `agents/dream_engine.py` | L309 | ✅ fixed | `except Exception as e:` | 正当な安全ネット（修正不要） | 2026-06-27 |
| TD-1396 | `agents/dream_engine.py` | L355 | ✅ fixed | `except Exception as e:` | 正当な安全ネット（修正不要） | 2026-06-27 |
| TD-1397 | `agents/dream_engine.py` | L363 | ✅ fixed | `except Exception as e:` | 正当な安全ネット（修正不要） | 2026-06-27 |
| TD-1398 | `agents/dream_engine.py` | L561 | ✅ fixed | `except Exception as e:` | 正当な安全ネット（修正不要） | 2026-06-27 |
| TD-1399 | `agents/dream_engine.py` | L581 | ✅ fixed | `except Exception as e:` | 正当な安全ネット（修正不要） | 2026-06-27 |
| TD-1400 | `archives/archive_stable_v3.0_20260118_0953/quality_gate_agent.py` | L105 | ✅ fixed | `except Exception as e:` |  | 2026-06-23 |
| TD-1430 | `agents/orchestration/mark_tasks_p27_multi2.py` | L46 | 🔴 open | `except Exception as e:` | バッチスクリプト全体の安全ネットとして正当化されるため修正不要 | - |
| TD-1442 | `agents/orchestration/consensus_engine.py` | L518 | 🔴 open | `except Exception as e:` | Replace with specific exceptions | - |
| TD-1443 | `agents/orchestration/consensus_engine.py` | L552 | 🔴 open | `except Exception as e:` | Replace with specific exceptions | - |
| TD-1444 | `agents/orchestration/consensus_engine.py` | L599 | 🔴 open | `except Exception` | Replace with specific exceptions | - |
| TD-1445 | `agents/orchestration/consensus_engine.py` | L682 | 🔴 open | `except Exception` | Replace with specific exceptions | - |
| TD-1446 | `agents/orchestration/consensus_engine.py` | L708 | 🔴 open | `except Exception` | Replace with specific exceptions | - |
| TD-1447 | `agents/orchestration/daemon_manager.py` | L237 | 🔴 open | `except Exception` | Replace with specific exceptions (OSError, psutil.Error, etc.) | - |
| TD-1448 | `agents/orchestration/daemon_manager.py` | L481 | 🔴 open | `except Exception` | Replace with specific exceptions (OSError, psutil.Error, etc.) | - |
| TD-1449 | `agents/orchestration/daemon_manager.py` | L548 | 🔴 open | `except Exception` | Replace with specific exceptions (OSError, psutil.Error, etc.) | - |
| TD-1450 | `agents/orchestration/daemon_manager.py` | L599 | 🔴 open | `except Exception` | Replace with specific exceptions (OSError, psutil.Error, etc.) | - |
| TD-1451 | `agents/orchestration/daemon_manager.py` | L682 | 🔴 open | `except Exception` | Replace with specific exceptions (OSError, psutil.Error, etc.) | - |
| TD-1452 | `agents/orchestration/daemon_manager.py` | L708 | 🔴 open | `except Exception` | Replace with specific exceptions (OSError, psutil.Error, etc.) | - |
| TD-1455 | `video_pipeline/ingest_service.py` | L181 | 🔴 open | `except Exception as e:` | Replace with specific exceptions (subprocess.CalledProcessError, OSError) | - |
| TD-1456 | `video_pipeline/audio_extractor.py` | L117 | 🔴 open | `except Exception as e:` | Replace with specific exceptions (subprocess.CalledProcessError, OSError) | - |
| TD-1457 | `video_pipeline/audio_extractor.py` | L181 | 🔴 open | `except Exception as e:` | Replace with specific exceptions (subprocess.CalledProcessError, OSError) | - |
| TD-1458 | `video_pipeline/video_composer.py` | L172 | 🔴 open | `except Exception as e:` | Replace with specific exceptions (subprocess.CalledProcessError, OSError) | - |
| TD-1459 | `video_pipeline/video_composer.py` | L220 | 🔴 open | `except Exception as e:` | Replace with specific exceptions (subprocess.CalledProcessError, OSError) | - |
| TD-1460 | `video_pipeline/video_composer.py` | L264 | 🔴 open | `except Exception as e:` | Replace with specific exceptions (subprocess.CalledProcessError, OSError) | - |
| TD-1461 | `video_pipeline/video_composer.py` | L315 | 🔴 open | `except Exception as e:` | Replace with specific exceptions (subprocess.CalledProcessError, OSError) | - |
| TD-1462 | `video_pipeline/video_composer.py` | L358 | 🔴 open | `except Exception as e:` | Replace with specific exceptions (subprocess.CalledProcessError, OSError) | - |
| TD-1463 | `video_pipeline/transcription_service.py` | L147 | 🔴 open | `except Exception` | Replace with specific exceptions | - |
| TD-1464 | `video_pipeline/subtitle_generator.py` | L157 | 🔴 open | `except Exception` | Replace with specific exceptions | - |
| TD-1465 | `video_pipeline/telop_renderer.py` | L168 | ✅ fixed | `except Exception` | Replace with specific exceptions | 2026-06-27 |
| TD-1466 | `video_pipeline/thumbnail_generator.py` | L158 | 🔴 open | `except Exception` | Replace with specific exceptions | - |
| TD-1467 | `video_pipeline/thumbnail_generator.py` | L252 | 🔴 open | `except Exception` | Replace with specific exceptions | - |
| TD-1468 | `video_pipeline/thumbnail_generator.py` | L297 | 🔴 open | `except Exception` | Replace with specific exceptions | - |
| TD-1469 | `video_pipeline/pipeline_coordinator.py` | L260 | 🔴 open | `except Exception` | Replace with specific exceptions | - |
| TD-1470 | `video_pipeline/audio_extractor.py` | L273 | 🔴 open | `except Exception as e:` | エラーをログ出力しNoneを返すことで安全にハンドリング | - |
| TD-1471 | `video_pipeline/soul_feedback_engine.py` | L343 | ✅ fixed | `except Exception as e:` | None | 2026-06-28 |
| TD-1472 | `video_pipeline/soul_feedback_engine.py` | L398 | ✅ fixed | `except Exception as e:` | None | 2026-06-28 |
| TD-1475 | `routers/pipeline_router.py` | L1434 | 🔴 open | `except Exception:` | None | - |
| TD-1476 | `routers/pipeline_router.py` | L1460 | 🔴 open | `except Exception as e:` | None | - |
| TD-1479 | `video_pipeline/stable_ts_wrapper.py` | L104 | 🔴 open | `except Exception as e:` | 必要に応じてフォールバック | - |
| TD-1480 | `video_pipeline/stable_ts_wrapper.py` | L167 | 🔴 open | `except Exception as e:` | 必要に応じてフォールバック | - |
| TD-593 | `routers/pipeline_router.py` | L1120 | 🔵 accepted | `except Exception` | 修正不要（HTTPException re-raise済み） | - |
| TD-594 | `routers/pipeline_router.py` | L1134 | 🔵 accepted | `except Exception` | 修正不要（HTTPException re-raise済み） | - |
| TD-595 | `routers/smartcut.py` | L131 | 🔵 accepted | `except Exception` | 修正不要（HTTPException re-raise済み） | - |
| TD-596 | `routers/smartcut.py` | L165 | 🔵 accepted | `except Exception` | 修正不要（HTTPException re-raise済み） | - |
| TD-597 | `routers/smartcut.py` | L189 | 🔵 accepted | `except Exception` | 修正不要（HTTPException re-raise済み） | - |
| TD-598 | `routers/smartcut.py` | L235 | 🔵 accepted | `except Exception` | 修正不要（HTTPException re-raise済み） | - |
| TD-599 | `routers/youtube_optimizer.py` | L842 | 🔵 accepted | `except Exception` | 修正不要（HTTPException re-raise済み） | - |
| TD-671 | `cache_manager.py` | L70 | ✅ fixed | `except Exception as e:` | 修正不要（恒久的な安全ネット） | 2026-06-05 |
| TD-672 | `cache_manager.py` | L72 | ✅ fixed | `except Exception:` | 修正不要（恒久的な安全ネット） | 2026-06-05 |
| TD-673 | `cache_manager.py` | L89 | ✅ fixed | `except Exception as e:` | 修正不要（恒久的な安全ネット） | 2026-06-05 |
| TD-674 | `cache_manager.py` | L91 | ✅ fixed | `except Exception:` | 修正不要（恒久的な安全ネット） | 2026-06-05 |
| TD-675 | `cache_manager.py` | L105 | ✅ fixed | `except Exception as e:` | 修正不要（恒久的な安全ネット） | 2026-06-05 |
| TD-676 | `cache_manager.py` | L114 | ✅ fixed | `except Exception as e:` | 修正不要（恒久的な安全ネット） | 2026-06-05 |
| TD-677 | `cache_manager.py` | L165 | ✅ fixed | `except Exception as e:` | 修正不要（恒久的な安全ネット） | 2026-06-05 |
| TD-678 | `cache_manager.py` | L185 | ✅ fixed | `except Exception as e:` | 修正不要（恒久的な安全ネット） | 2026-06-05 |
| TD-679 | `cache_manager.py` | L197 | ✅ fixed | `except Exception as e:` | 修正不要（恒久的な安全ネット） | 2026-06-05 |
| TD-711 | `agents/stage_bound_agent.py` | L73 | ✅ fixed | `except Exception:` | 修正不要（SQLite接続クローズの安全ネット） | 2026-06-08 |
| TD-713 | `model_governance_local.py` | L133 | ✅ fixed | `except Exception:` | 修正不要（SQLite接続クローズの安全ネット） | 2026-06-08 |
| TD-732 | `agents/orchestration/token_limiter.py` | L38 | ✅ fixed | `except Exception as e:` | tiktokenの実行例外に対するフォールバック保護のため、accepted_safetyとする | 2026-05-31 |
| TD-740 | `check_pipeline_status.py` | L13 | 🔵 accepted | `except Exception as e:` | No fix required (safety net for unexpected connection errors) | 2026-06-07 |
| TD-741 | `check_pipeline_status.py` | L23 | 🔵 accepted | `except Exception as e:` | No fix required (safety net for unexpected JSON parsing/decoding errors) | 2026-06-07 |
| TD-748 | `phase0_preflight.py` | L221 | 🔵 accepted | `if __name__ == "__main__":` | テスト対象外（直接実行エントリーポイント）として許容 | 2026-05-25 |
| TD-826 | `agents/workers/quality_gate_worker.py` | L79 | ✅ fixed | `except Exception as e:` | 適切な例外捕捉またはログ出力 | 2026-06-07 |
| TD-828 | `pipeline_error_strategy.py` | L0 | 🔴 open | `except Exception` |  | - |
| TD-829 | `services/nhk_quality_scorer.py` | L0 | ✅ fixed | `except Exception` |  | 2026-06-07 |
| TD-830 | `services/quality_feedback_trigger.py` | L0 | ✅ fixed | `except Exception` |  | 2026-06-04 |
| TD-831 | `project_archiver.py` | L195 | ✅ fixed | `except Exception as e:` | Pillow verification is third-party safe check | 2026-06-23 |
| TD-832 | `project_archiver.py` | L201 | ✅ fixed | `except Exception as e:` | Pillow verification is third-party safe check | 2026-06-23 |
| TD-833 | `inspect_video.py` | L28 | 🔵 accepted | `except Exception as e:` | Pillow verification exception handling | 2026-05-29 |
| TD-834 | `inspect_video.py` | L34 | 🔵 accepted | `except Exception as e:` | Pillow image open exception handling | 2026-05-29 |
| TD-861 | `philosophy_manager.py` | L582 | ✅ fixed | `except Exception as e:` | 安全ネットのための広範なキャッチ（正常） | 2026-06-27 |
| TD-862 | `philosophy_manager.py` | L586 | ✅ fixed | `except Exception:` | 一時ファイルクリーンアップの安全無視（正常） | 2026-06-27 |
| TD-863 | `philosophy_manager.py` | L606 | ✅ fixed | `except Exception as e:` | Pillow verify例外のValueError変換（正常） | 2026-06-27 |
| TD-864 | `philosophy_manager.py` | L613 | ✅ fixed | `except Exception as e:` | Pillow load例外のValueError変換（正常） | 2026-06-27 |
| TD-867 | `ai_rhythm.py` | L43 | ✅ fixed | `except Exception as e:` |  | 2026-06-02 |
| TD-868 | `ai_rhythm.py` | L117 | ✅ fixed | `except Exception as e:` |  | 2026-06-02 |
| TD-869 | `quick_check.py` | L85 | 🔴 open | `except Exception as e:` |  | - |
| TD-870 | `quick_check.py` | L89 | 🔴 open | `except Exception:` |  | - |
| TD-871 | `quick_check.py` | L112 | 🔴 open | `except Exception as e:` |  | - |
| TD-872 | `quick_check.py` | L120 | 🔴 open | `except Exception as e:` |  | - |
| TD-873 | `agents/orchestration/mark_tasks_p27_multi3.py` | L93 | 🔴 open | `except Exception as e:` | 原子的な書き込みにおけるエラー捕捉のための安全ネット | - |
| TD-874 | `agents/orchestration/mark_tasks_p27_multi3.py` | L97 | 🔴 open | `except Exception:` | 一時ファイル削除失敗の無視 | - |
| TD-875 | `agents/orchestration/mark_tasks_p27_multi3.py` | L126 | 🔴 open | `except Exception as e:` | 画像検証のエラーハンドリング | - |
| TD-876 | `agents/orchestration/mark_tasks_p27_multi3.py` | L134 | 🔴 open | `except Exception as e:` | 画像ロードのエラーハンドリング | - |
| TD-897 | `agents/adk_agent_template.py` | L46 | ✅ fixed | `except Exception:` |  | 2026-06-23 |
| TD-898 | `agents/adk_agent_template.py` | L55 | ✅ fixed | `except Exception:` |  | 2026-06-23 |

---

## 負債発生要因パターンカタログ

| ID | パターン名 | 発生要因 | 防止策 | 影響範囲 |
|:--|:---|:---|:---|:---|
| DP-01 | **汎用catch伝播** | 1箇所のexcept Exceptionがコピペされる | Router新規作成テンプレートにguard必須化 | 全Router |
| DP-02 | **HTTPException捕捉** | except ExceptionがHTTPException(4xx)を500に変換 | conftest.pyチェッカーにguard検証ルール追加 | Router層 |
| DP-03 | **テスト500許容連鎖** | エンドポイント500→テストin(200,500)許容→バグ隠蔽 | TECH_DEBTマーカー付き許容禁止。本番修正先行 | テスト全体 |
| DP-04 | **モジュール間型不一致** | 呼出し先メソッド名変更時に呼出し元が追従しない | 型ヒント + mypy/pyright静的解析導入 | 全モジュール間 |
| DP-05 | **ログなしcatch** | except Exception: pass でログすら出さない | lintルールでログ出力必須化 | Service/Engine層 |
| DP-06 | **Singleton初期化例外** | __new__や__init__で例外catchし破損状態で続行 | 初期化失敗は即raise。遅延初期化パターン採用 | ModelRegistry等 |

---

## 更新履歴

> このファイルはJSON (`technical_debt_index.json`) から自動生成されています。
> 手動編集禁止。`TechnicalDebtStore` API経由で更新してください。
