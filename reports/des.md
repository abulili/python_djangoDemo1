同 request_id 并发幂等测试
同一 request_id 并发提交时不会重复创建 Celery 任务。

```python
python scripts\light_load_test.py --username testuser --password **\*\*** --total 20 --workers 5 --same-request-id --report-file reports\load-test-idempotent.json
```

不同 request_id 并发提交限流测试
不同请求高并发提交时会触发提交接口限流，保护 AI 调用入口

```python
python scripts\light_load_test.py --username testuser --password **\*\*** --total 30 --workers 10 --report-file reports\load-test-submit.json
```

任务轮询接口限流测试
任务状态查询接口具备独立限流能力，可以保护轮询接口

```python
python scripts\light_load_test.py --username testuser --password **\*\*** --mode poll-task --task-id e578fbef-f77a-48d5-a1e5-b9234871d339 --total 130 --workers 20 --report-file reports\load-test-poll-limit.json
```
