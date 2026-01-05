# LLM Interceptor UI

A modern, React-based interface for analyzing captured AI coding tool sessions.

## Features

- **Real-time Monitoring**: Automatically detects and displays active sessions from `lli watch`.
- **Deep Inspection**: View detailed request/response headers, bodies, and latency.
- **Rich Visualization**:
    - **Chat View**: Rendered Markdown conversations with role-based styling.
    - **System Prompt**: Dedicated view for system instructions.
    - **Tool Usage**: Interactive tool call and result visualization.
    - **Raw JSON**: Full access to the underlying data structure.
- **Filter**: Filter requests by System Prompt hash to identify different agent personas.
- **Theme**: Light and Dark mode support.

## Usage

This UI is bundled with the `llm-interceptor` Python package.

1.  **Start Watch Mode**:
    ```bash
    lli watch --include "*example.com*"
    ```

    To expose the UI on your network:
    ```bash
    lli watch --ui-host 0.0.0.0 --ui-port 8000
    ```

2.  **Open the Dashboard**:
    The CLI will print a URL (usually `http://localhost:8000`). Click it to open the dashboard.

3.  **Analyze**:
    - Select a session from the sidebar.
    - Click on any request to view its details.
    - Use the tabs (Chat, System, Tools, JSON) to explore different aspects of the interaction.

## Development

If you want to modify this UI:

1.  Install dependencies:
    ```bash
    cd ui
    npm install
    ```

2.  Start the development server:
    ```bash
    npm run dev
    ```

3.  Build for production (integrates into Python package):
    ```bash
    # From project root
    python3 build_ui.py
    ```
