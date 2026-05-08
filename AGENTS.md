# auto-triage

auto-triage is an agent for keeping track of issues and pull requests in a github repository and automatically try the fixes to them based on the tags provided to the issue.

Each issue that is intended to be worked on by the auto-triage agent should be with the tag `auto-triage-ready`. The agent runs at intervals and when it finds new issues in the repository it can act on, it then pulls latest update from the repository, creates a new branch for the issue, and tries to fix the issue based on the tags provided to it. If the agent is able to fix the issue, it then creates a pull request with the fix and adds the tag `auto-triage-fixed` to the issue. If the agent is not able to fix the issue, it adds the tag `auto-triage-unable-to-fix` to the issue.
The agent can be configured to run at specific intervals and can be set to only work on specific repositories. It can also be configured to only work on issues with specific tags, and to ignore issues with certain tags.

# Tech Stack

- Agent is going to be written in python. Agent should hand off the task to sub agent. Use langgraph for agent orchestration.
- The agent will use github mcp server for now. Assume that the mcp server is already setup and available to use. The agent will use it to interact with github repository.
- Github repository, github api key, github issue tags to work on, github issue tags to use if agent cannot solve the problem will be provided to agent as environment variables and will be available through config object in the code.
- The agent will use github mcp server to pull latest open issues and check for tags on them. The issues it can work on will be persisted in the disk on host machine agent is running on. This will also allow agent to keep track of which issues it has already tried to fix and which ones are new. This will also enable agent to continue working on the issue it was working on if it somehow gets interrupted or restarted.
- the long running api that agent will be used to call is going to be with fastapi. This will allow us to easily expose some endpoints for monitoring and debugging the agent in the future if needed.

# Structure

## application directory structure

The application will have following directory structure:
- app/
  - main.py
  - config.py
  - scheduler.py
  - graph.py
  - state.py
  - nodes/
    - discover_issues.py
    - claim_issue.py
  - tools/
    - github_tool.py
    - shell.py
  - persistence/
    - job_store.py
    - temporal.py
    - checkpoint.py

## triage states

These are the states triage can be in:
- queued: a new issue is found and added to the queue to be worked on by the agent.
- in_progress: an agent is currently working on the issue.
- resolved: the issue has been resolved and a pull request has been created with the fix.
- unable_to_fix: the agent was not able to fix the issue.

## langgraph states

use official sdk from openai to connect with the completion api. Do not use langchain's code sdk, I don't want to depend on langchain for this project. Use langgraph's state management and orchestration features to manage the states of the triage process through official openai completion sdk. This will allow integration for completion through anthropic or gemini's provider in the future if needed without much change in the codebase.

## Environment variables

GITHUB_TOKEN: string
GITHUB_REPOSITORIES: comma separated string of repositories to work on. For example: "owner1/repo1,owner2/repo2"
GITHUB_ISSUE_TAGS_TO_WORK_ON: comma separated string of tags that denote which issues the agent should work on. For example: "auto-triage-ready,bug"
