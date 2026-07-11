# Planner OS Secure MCP Tunnel

Planner OS uses OpenAI Secure MCP Tunnel to make the existing local STDIO MCP
server available to normal ChatGPT chats. The workbook and MCP server remain on
this Mac; the tunnel client makes an outbound HTTPS connection to OpenAI.

## One-time OpenAI setup

1. Open https://platform.openai.com/settings/organization/tunnels.
2. Create a tunnel associated with the ChatGPT workspace that will use Planner
   OS. Copy its `tunnel_id`.
3. Ensure your Platform role has Tunnels Read + Use. Creating the tunnel also
   requires Tunnels Read + Manage.
4. Open https://platform.openai.com/settings/organization/api-keys and create a
   runtime API key for the tunnel client.
5. Enable ChatGPT developer mode if it is not already enabled.

## Configure Planner OS

From the project directory:

```sh
./planner-tunnel setup tunnel_your_id_here
export CONTROL_PLANE_API_KEY='your-runtime-key'
./planner-tunnel doctor
./planner-tunnel run
```

Keep the final command running while ChatGPT uses Planner OS. In another
terminal, `./planner-tunnel health-url` prints the local admin URL; append `/ui`
to inspect tunnel health.

Do not put the runtime API key in this repository or in a committed shell file.

## Connect ChatGPT

While the tunnel is running, open https://chatgpt.com/plugins, create a
developer-mode app, choose **Tunnel** as the connection type, and select the
Planner OS tunnel. The app then becomes available to normal ChatGPT chats.
