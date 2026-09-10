"""게임 업무 서비스를 유스케이스 경계별로 관리하는 패키지.

실제 runtime 조합은 `postgres_runtime`이 담당하며, command·window·AI 진행·sync
변환·결과 projection은 각 모듈에서 제공한다. snapshot·creation의 공개 import
경계도 이 패키지에 두되, 현재 구현 본문은 기존 DB 계약 보존을 위해 단계적으로
이동한다.
"""
