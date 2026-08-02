"""
Data Migration - 既存データの新アーキテクチャへの移行

PROJECT_CONSTITUTION 準拠:
- 既存データの保護: 移行前に必ず自動でバックアップを作成します。
- 段階的移行: 各ステップ（デザイントークン、履歴ログ、モデル設定、プラグイン、コアモジュール）を個別に検証・移行します。

このモジュールは、システムが新しい統合アーキテクチャにアップデートされた際に、
古いデータ構造や設定ファイルを新しい仕様に安全に適合・検証するための移行ユーティリティを提供します。
"""
try:  # backend/ を直接 sys.path に載せている経路にも対応する
    from backend.path_resolver import writable_path as _writable_path
except ImportError:
    from path_resolver import writable_path as _writable_path

from typing import Dict, Any, List, Optional
from pathlib import Path
from datetime import datetime
import json
import shutil
import logging

logger = logging.getLogger(__name__)


class DataMigration:
    """
    データ移行および検証を行うメインクラス。
    
    既存のデータを新しい統合アーキテクチャに適合させ、必要なファイルの存在と整合性を検証します。
    """
    
    def __init__(self):
        """
        DataMigration クラスを初期化します。
        
        移行対象のベースディレクトリ（backend）、ブランディング用ディレクトリ（branding）、
        およびバックアップ先ディレクトリ（migration_backups）のパスを設定します。
        """
        self._backend_dir = Path(__file__).parent
        self._branding_dir = self._backend_dir / "branding"
        self._backup_dir = self._backend_dir / "migration_backups"
    
    def run_migration(self, dry_run: bool = True) -> Dict[str, Any]:
        """
        移行プロセス全体を実行、または検証します。
        
        このメソッドは、以下の処理を順次実行します。
        1. `dry_run` が False の場合、`_create_backup` を呼び出して現在のブランディングデータを退避します。
        2. `_verify_design_tokens` を呼び出し、デザイントークンの整合性を確認します。
        3. `_verify_evolution_log` を呼び出し、エボリューションログを確認します。
        4. `_verify_model_config` を呼び出し、モデル設定を確認します。
        5. `_verify_plugins` を呼び出し、プラグインの存在を確認します。
        6. `_verify_core` を呼び出し、コアモジュールの整合性を確認します。
        
        Args:
            dry_run: True の場合、ファイル書き込みやバックアップ作成を伴う実際の移行処理を行わず、検証のみを実行します。
                     False の場合、バックアップを作成した上で移行を行います。
        
        Returns:
            移行結果を含むディクショナリ。以下のキーを含みます。
            - status (str): 全体ステータス ("started", "completed", "needs_attention", "failed")
            - timestamp (str): 実行開始時刻のISOフォーマット文字列
            - dry_run (bool): dry_run 引数の値
            - steps (List[Dict[str, Any]]): 各ステップの詳細結果リスト
            - summary (str): パスしたステップのサマリー（例: "5/5 checks passed"）
        """
        logger.info(f"Starting data migration (dry_run={dry_run})")
        
        result = {
            "status": "started",
            "timestamp": datetime.now().isoformat(),
            "dry_run": dry_run,
            "steps": []
        }
        
        # バックアップ作成
        if not dry_run:
            try:
                backup_path = self._create_backup()
                result["steps"].append({"name": "backup", "status": "completed", "path": backup_path})
            except OSError as e:
                logger.error(f"Backup creation failed: {e}")
                result["steps"].append({"name": "backup", "status": "failed", "reason": f"Backup failed: {str(e)}"})
                result["status"] = "failed"
                result["summary"] = "Backup creation failed, migration aborted"
                return result
        
        # 各検証ステップを安全に実行
        steps_to_run = [
            ("design_tokens", self._verify_design_tokens),
            ("evolution_log", lambda: self._verify_evolution_log(dry_run=dry_run)),
            ("model_config", self._verify_model_config),
            ("plugins", self._verify_plugins),
            ("core", self._verify_core)
        ]
        
        for name, func in steps_to_run:
            try:
                step_res = func()
                result["steps"].append(step_res)
            except Exception as e:
                logger.error(f"Error executing step {name}: {e}")
                result["steps"].append({
                    "name": name,
                    "status": "failed",
                    "reason": f"Unexpected error during verification: {str(e)}"
                })
        
        # 結果判定
        all_passed = all(s.get("status") in ("passed", "completed") for s in result["steps"])
        result["status"] = "completed" if all_passed else "needs_attention"
        result["summary"] = f"{sum(1 for s in result['steps'] if s.get('status') in ('passed', 'completed'))}/{len(result['steps'])} checks passed"
        
        logger.info(f"Migration check completed: {result['summary']}")
        return result
    
    def _create_backup(self) -> str:
        """
        ブランディングディレクトリのバックアップを作成します。
        
        `migration_backups` ディレクトリ配下に、現在の日時を付与したフォルダ（例: `backup_20260627_120000`）を作成し、
        現在の `branding` ディレクトリの内容をコピーします。
        
        Returns:
            作成されたバックアップ先の絶対パスを表す文字列。
            
        Raises:
            OSError: ディレクトリの作成やファイルのコピーに失敗した場合。
            Exception: その他の予期せぬエラーが発生した場合。
        """
        try:
            self._backup_dir.mkdir(exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = self._backup_dir / f"backup_{timestamp}"
            
            # branding ディレクトリをバックアップ
            if self._branding_dir.exists():
                shutil.copytree(self._branding_dir, backup_path / "branding")
            
            logger.info(f"Backup created: {backup_path}")
            return str(backup_path)
        except OSError as e:
            logger.error(f"Error creating backup: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error creating backup: {e}")
            raise
    
    def _verify_design_tokens(self) -> Dict[str, Any]:
        """
        デザイントークンの設定を検証します。
        
        `branding/constitution.json` が存在すること、有効なJSONオブジェクトであること、
        および `design_tokens` セクションに必須のムード（"elegant", "dynamic", "dramatic"）が
        定義されていることを確認します。
        
        Returns:
            検証結果ディクショナリ。
            ステータス値は以下のいずれかになります。
            - "passed": 必要なムードがすべて揃っている場合。
            - "warning": design_tokens自体は存在するが、必須ムードが一部欠けている場合。
            - "failed": ファイルが存在しない、JSONデコードエラー、あるいは構造が正しくない場合。
        """
        constitution_path = self._branding_dir / "constitution.json"
        
        try:
            if not constitution_path.exists():
                return {"name": "design_tokens", "status": "failed", "reason": "constitution.json not found"}
            
            with open(constitution_path, "r", encoding="utf-8") as f:
                constitution = json.load(f)
            
            if not isinstance(constitution, dict):
                return {"name": "design_tokens", "status": "failed", "reason": "constitution.json content is not a JSON object"}
            
            design_tokens = constitution.get("design_tokens", {})
            
            if not isinstance(design_tokens, dict):
                return {"name": "design_tokens", "status": "failed", "reason": "design_tokens section is not a JSON object"}
            
            if not design_tokens:
                return {"name": "design_tokens", "status": "failed", "reason": "design_tokens section is empty"}
            
            # 必須ムードの確認
            required_moods = ["elegant", "dynamic", "dramatic"]
            missing = [m for m in required_moods if m not in design_tokens]
            
            if missing:
                return {"name": "design_tokens", "status": "warning", "reason": f"Missing moods: {missing}"}
            
            return {"name": "design_tokens", "status": "passed", "moods": list(design_tokens.keys())}
            
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Error reading design tokens: {e}")
            return {"name": "design_tokens", "status": "failed", "reason": str(e)}
        except Exception as e:
            logger.error(f"Unexpected error reading design tokens: {e}")
            return {"name": "design_tokens", "status": "failed", "reason": f"Unexpected error: {str(e)}"}
    
    def _verify_evolution_log(self, dry_run: bool) -> Dict[str, Any]:
        """
        システムの変更履歴ログ（evolution_log.json）の存在と妥当性を検証します。
        
        `branding/evolution_log.json` が存在すること、および有効なJSONオブジェクトであることを確認します。
        存在しない場合で、かつ `dry_run` が False であれば、初期履歴ログファイルを新規作成します。
        
        Args:
            dry_run: True の場合、ファイルが存在しなくても新規作成を行いません。
        
        Returns:
            検証結果ディクショナリ。
            ステータス値およびアクション値を含みます。
            - status: "passed" または "failed"
            - action: "exists"（ファイルが存在する場合）、"will_create"（dry_runで未存在の場合）、
                      "created"（新規作成された場合）
        """
        # 実行のたびに追記される進化履歴。設定ファイルと違って書き換わるので、
        # 読み書きの両方をこの経路へ通す。
        log_path = _writable_path("backend/branding/evolution_log.json")

        if not log_path.exists():
            if dry_run:
                return {"name": "evolution_log", "status": "passed", "action": "will_create"}

            # 新規作成（dry_run=False の場合のみディレクトリとファイルを作成）
            try:
                log_path.parent.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                logger.error(f"Failed to create branding directory: {e}")
                return {"name": "evolution_log", "status": "failed", "reason": f"Failed to create branding directory: {str(e)}"}
            
            initial = {
                "version": "4.0",
                "entries": [],
                "philosophies": [],
                "created": datetime.now().isoformat()
            }
            tmp_path = log_path.with_suffix(".tmp")
            try:
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(initial, f, ensure_ascii=False, indent=2)
                tmp_path.replace(log_path)
            except OSError as e:
                logger.error(f"Failed to write evolution_log.json: {e}")
                if tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except OSError:
                        pass
                return {"name": "evolution_log", "status": "failed", "reason": f"Failed to create evolution log: {str(e)}"}
            return {"name": "evolution_log", "status": "passed", "action": "created"}
        
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                evolution_log = json.load(f)
            if not isinstance(evolution_log, dict):
                return {"name": "evolution_log", "status": "failed", "reason": "evolution_log.json content is not a JSON object"}
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"evolution_log.json is corrupted: {e}")
            return {"name": "evolution_log", "status": "failed", "reason": f"evolution_log.json is corrupted: {str(e)}"}
        except Exception as e:
            logger.error(f"Unexpected error verifying evolution log: {e}")
            return {"name": "evolution_log", "status": "failed", "reason": f"Unexpected error: {str(e)}"}
        
        return {"name": "evolution_log", "status": "passed", "action": "exists"}
    
    def _verify_model_config(self) -> Dict[str, Any]:
        """
        AIモデル設定ファイル（model_config.json）の存在と必須項目の整合性を検証します。
        
        `model_config.json` が存在すること、有効なJSONオブジェクトであること、
        および必須キー（"version", "models", "task_mapping"）がすべて含まれていることを確認します。
        
        Returns:
            検証結果ディクショナリ。
            ステータス値は以下のいずれかになります。
            - "passed": 必須のキーがすべて揃っている場合。
            - "warning": model_config.jsonは存在するが、一部の必須キーが欠けている場合。
            - "failed": ファイルが存在しない、JSONデコードエラー、あるいは構造が正しくない場合。
        """
        config_path = self._backend_dir / "model_config.json"
        
        try:
            if not config_path.exists():
                return {"name": "model_config", "status": "failed", "reason": "model_config.json not found"}
            
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            
            if not isinstance(config, dict):
                return {"name": "model_config", "status": "failed", "reason": "model_config.json content is not a JSON object"}
            
            required_keys = ["version", "models", "task_mapping"]
            missing = [k for k in required_keys if k not in config]
            
            if missing:
                return {"name": "model_config", "status": "warning", "reason": f"Missing keys: {missing}"}
            
            return {"name": "model_config", "status": "passed", "version": config.get("version")}
            
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Error reading model config: {e}")
            return {"name": "model_config", "status": "failed", "reason": str(e)}
        except Exception as e:
            logger.error(f"Unexpected error reading model config: {e}")
            return {"name": "model_config", "status": "failed", "reason": f"Unexpected error: {str(e)}"}
    
    def _verify_plugins(self) -> Dict[str, Any]:
        """
        プラグインディレクトリおよび配置されたプラグインモジュールを検証します。
        
        `plugins` ディレクトリが存在し、かつそれが有効なディレクトリであることを確認します。
        また、`plugins` 内に `*_plugin.py` というパターンに一致するプラグインファイルが
        少なくとも3つ以上配置されていることを確認します。
        
        Returns:
            検証結果ディクショナリ。
            ステータス値は以下のいずれかになります。
            - "passed": プラグインディレクトリが存在し、3つ以上のプラグインが検知された場合。
            - "warning": プラグインディレクトリは存在するが、検知されたプラグイン数が3つ未満の場合。
            - "failed": ディレクトリが存在しない、またはアクセスエラー等が発生した場合。
        """
        plugins_dir = self._backend_dir / "plugins"
        
        try:
            if not plugins_dir.exists():
                return {"name": "plugins", "status": "failed", "reason": "plugins directory not found"}
            if not plugins_dir.is_dir():
                return {"name": "plugins", "status": "failed", "reason": "plugins path is not a directory"}
            
            plugins = [p for p in plugins_dir.glob("*_plugin.py") if p.is_file()]
        except OSError as e:
            logger.error(f"Error accessing plugins directory: {e}")
            return {"name": "plugins", "status": "failed", "reason": str(e)}
        except Exception as e:
            logger.error(f"Unexpected error verifying plugins: {e}")
            return {"name": "plugins", "status": "failed", "reason": f"Unexpected error: {str(e)}"}
        
        if len(plugins) < 3:
            return {"name": "plugins", "status": "warning", "reason": f"Only {len(plugins)} plugins found"}
        
        return {"name": "plugins", "status": "passed", "count": len(plugins)}
    
    def _verify_core(self) -> Dict[str, Any]:
        """
        システムコアディレクトリ内の主要ファイルの整合性を検証します。
        
        `core` ディレクトリが存在し、かつそれが有効なディレクトリであることを確認します。
        また、そのディレクトリ内に必須となる主要ファイル（"context.py", "plugin.py", "registry.py", "__init__.py"）が
        すべて正しく配置されている（ファイルとして存在している）ことを確認します。
        
        Returns:
            検証結果ディクショナリ。
            ステータス値は以下のいずれかになります。
            - "passed": コアディレクトリおよび必須ファイルがすべて揃っている場合。
            - "failed": コアディレクトリが存在しない、アクセスエラー、あるいは必須ファイルが欠けている場合。
        """
        core_dir = self._backend_dir / "core"
        
        try:
            if not core_dir.exists():
                return {"name": "core", "status": "failed", "reason": "core directory not found"}
            if not core_dir.is_dir():
                return {"name": "core", "status": "failed", "reason": "core path is not a directory"}
            
            required_files = ["context.py", "plugin.py", "registry.py", "__init__.py"]
            missing = [f for f in required_files if not (core_dir / f).is_file()]
        except OSError as e:
            logger.error(f"Error accessing core directory: {e}")
            return {"name": "core", "status": "failed", "reason": str(e)}
        except Exception as e:
            logger.error(f"Unexpected error verifying core: {e}")
            return {"name": "core", "status": "failed", "reason": f"Unexpected error: {str(e)}"}
        
        if missing:
            return {"name": "core", "status": "failed", "reason": f"Missing files: {missing}"}
        
        return {"name": "core", "status": "passed", "files": required_files}


# シングルトンインスタンス
data_migration = DataMigration()
