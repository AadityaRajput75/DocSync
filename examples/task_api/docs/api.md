# Task API

## get_tasks
GET `/tasks` returns tasks using `list_tasks()`. The result limit defaults to 25.

## create_task
POST `/tasks` accepts a title and priority. Priority defaults to 1. The endpoint calls `save_task()`.

## health
GET `/health` returns `status: ready`.

## Deployment
The operations team owns environment configuration.
