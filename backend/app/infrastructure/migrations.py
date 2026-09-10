"""로컬 ``psql`` 실행 파일 없이 SQL 마이그레이션을 적용하는 실행기.

마이그레이션 파일 자체가 ``BEGIN``/``COMMIT``으로 원자성을 정의하므로 연결은
autocommit 모드로 연다. 실행기는 파일 이름 순서와 대상 DB만 책임지고, 실제
스키마 변경의 트랜잭션 경계와 재실행 안전성은 각 SQL 파일이 명시한다.
"""

from __future__ import annotations

from pathlib import Path

import psycopg

from backend.app.core.config import Settings

# 호출 위치와 무관하게 Backend가 소유하는 migrations 디렉터리를 찾는다.
BACKEND_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = BACKEND_ROOT / "migrations"


def run_migrations(settings: Settings, migrations_dir: Path = MIGRATIONS_DIR) -> list[str]:
    """이름순으로 SQL 마이그레이션을 실행하고 완료된 파일명을 반환한다.

    runtime과 DB 경로가 일치하는 전용 DDL DSN만 사용하며, 설정이 없거나 모호하면
    연결 전에 거부한다. 각 파일은 하나의 ``execute`` 호출로 전달하며 실패하면
    중단한다. 오류에는 DSN·SQL·driver 예외 원문을 넣지 않는다. 재실행 가능성은
    각 SQL의 ``IF NOT EXISTS`` 등에서 보장하고 파일 간 전체 rollback은 제공하지 않는다.
    """

    database_url = settings.effective_migration_database_url
    # 숫자 접두사를 사용한 파일명이 곧 실행 순서가 되도록 정렬한다.
    migration_paths = sorted(migrations_dir.glob("*.sql"))
    if not migration_paths:
        raise RuntimeError("No SQL migrations found")

    applied: list[str] = []
    # SQL 파일 내부의 BEGIN/COMMIT이 실제 최상위 트랜잭션이 되도록 드라이버의
    # 암시적 트랜잭션을 만들지 않는다.
    try:
        with psycopg.connect(database_url, autocommit=True) as connection:
            for migration_path in migration_paths:
                # 마이그레이션은 저장소에서 UTF-8 텍스트로 관리한다. SQL 내용이나
                # 연결 URL은 출력하지 않아 스키마 세부와 자격 증명 노출을 줄인다.
                sql = migration_path.read_text(encoding="utf-8")
                with connection.cursor() as cursor:
                    cursor.execute(sql)
                # execute가 예외 없이 끝난 파일만 호출자에게 완료로 보고한다.
                applied.append(migration_path.name)
    except Exception:
        # driver 오류에는 접속 정보나 SQL·데이터 조각이 섞일 수 있다. 파일 읽기와
        # context 종료 오류도 동일하게 숨기고 뒤 파일을 계속 실행하지 않는다.
        raise RuntimeError(
            "Migration execution failed; check database access and SQL files"
        ) from None
    return applied


def main() -> None:
    """DDL 자격 증명을 읽는 전용 환경 경로로 마이그레이션을 실행한다."""

    try:
        settings = Settings.from_migration_env()
        applied = run_migrations(settings)
    except Exception:
        # 공통 설정 검증 중 발생한 예외도 CLI traceback으로 노출하지 않는다.
        # 고정 메시지를 담은 SystemExit는 실패 상태로 종료하고 원문 chain을 숨긴다.
        raise SystemExit(
            "Migration failed; verify configuration, database access and SQL files"
        ) from None
    # 운영 로그에는 개수와 저장소의 파일명만 남긴다. runtime의 DATABASE_NAME을
    # 실제 DDL 대상으로 오인하게 출력하거나 호스트·계정·연결 URL을 기록하지 않는다.
    print(f"Applied {len(applied)} migration(s): {', '.join(applied)}")


if __name__ == "__main__":
    main()
