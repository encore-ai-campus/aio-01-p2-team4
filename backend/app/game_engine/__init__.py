"""게임 엔진의 목표 package 경계.

호환 facade는 import 순환을 피하기 위해 ``backend.app.game_engine.engine``에서
명시적으로 가져온다. 규칙 모듈은 package 초기화 시 외부 실행 코드를 호출하지 않는다.
"""
