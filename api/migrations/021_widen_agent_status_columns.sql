-- Allow durable wait statuses such as awaiting_user_response.
ALTER TABLE agent_tasks
    ALTER COLUMN status TYPE VARCHAR(40);

ALTER TABLE IF EXISTS agent_queue
    ALTER COLUMN status TYPE VARCHAR(40);
