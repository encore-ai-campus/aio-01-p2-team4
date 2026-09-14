FROM pgvector/pgvector:pg16

# 팀 DB의 실제 행은 이미지에 복사하지 않고, 저장소가 승인한 migration과 정적
# 시나리오·페르소나 seed만 초기화 스크립트로 포함한다. 컨테이너 최초 생성 때
# 실행되므로 Docker image layer에는 비밀번호나 사용자 게임 데이터가 남지 않는다.
COPY docker/postgres/init/000-create-app-role.sh /docker-entrypoint-initdb.d/000-create-app-role.sh
COPY backend/migrations/*.sql /docker-entrypoint-initdb.d/
COPY docker/postgres/init/999-grant-app-role.sh /docker-entrypoint-initdb.d/999-grant-app-role.sh

RUN chmod 0755 /docker-entrypoint-initdb.d/000-create-app-role.sh \
    /docker-entrypoint-initdb.d/999-grant-app-role.sh
