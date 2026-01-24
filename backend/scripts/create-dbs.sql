-- 创建业务数据库
CREATE DATABASE fastapi_db;
CREATE DATABASE celery_schedule_jobs;

-- ================================
-- 初始化 fastapi_db
-- ================================
\connect fastapi_db;

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_topology;

-- ================================
-- 初始化 celery_schedule_jobs
-- ================================
\connect celery_schedule_jobs;

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_topology;
