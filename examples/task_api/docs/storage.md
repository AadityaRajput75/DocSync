# Task storage

## list_tasks
Tasks are stored in memory and returned in insertion order, up to the requested limit.

## save_task
Each saved task contains title and priority. Leading and trailing whitespace is removed from the title.

## Durability
This demonstration store does not persist tasks across restarts.
