FROM redis:7-alpine

# Redis는 공개 원장이 아니지만 lock·cache·event pointer의 재기동 손실을 줄이기
# 위해 AOF를 켠다. 최종 데이터 정합성은 Backend의 PostgreSQL 원장이 보장한다.
COPY docker/redis/redis.conf /usr/local/etc/redis/redis.conf

CMD ["redis-server", "/usr/local/etc/redis/redis.conf"]
