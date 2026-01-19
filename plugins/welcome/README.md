# Welcome Plugin

The Welcome plugin manages welcome messages for Signal groups. It tracks group membership and automatically sends a greeting when new members join.

## Features

- **New Member Detection:** Monitors group update events to identify when someone new joins.
- **Customizable Welcome Message:** Allows setting a specific welcome message for each group.
- **Member Persistence:** Stores the current member list in `members.csv` for each group to track changes.

## Commands

- `!ph#initgroup`: Initializes the plugin for the current group.
    - Saves the current list of group members.
    - If a text file (e.g., `.txt` or `.md`) is attached to the command, it is saved as the group's welcome message.

## How it works

1. When `!ph#initgroup` is run, it records all current members.
2. The plugin listens for group `UPDATE` events.
3. Upon an update, it compares the current members with the saved list.
4. If new members are found, it sends the `welcome_message.txt` if it exists.
5. It then updates the saved member list.
