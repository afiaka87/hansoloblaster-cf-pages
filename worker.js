/**
 * Cloudflare Worker: Stream Status Proxy
 * 
 * This Worker serves as a secure proxy to check the current status of your Cloudflare Stream live input.
 * It calls the Cloudflare Stream API using credentials stored in environment variables and returns the
 * stream status as a JSON response.
 *
 * Environment Variables (set these in your Worker bindings):
 *   - ACCOUNT_ID: Your Cloudflare account ID.
 *   - LIVE_INPUT_ID: The identifier of your live input.
 *   - CLOUDFLARE_EMAIL: Your Cloudflare account email.
 *   - CLOUDFLARE_API_KEY: Your Cloudflare API key.
 */

async function handleRequest(request, env) {
  // Construct the Cloudflare API URL for your live input status.
  // The API endpoint returns detailed info about your live stream input.
  const apiUrl = `https://api.cloudflare.com/client/v4/accounts/${env.ACCOUNT_ID}/stream/live_inputs/${env.LIVE_INPUT_ID}`;

  // Prepare the headers for authentication.
  // Cloudflare requires both your account email and API key.
  const headers = {
    "X-Auth-Email": env.CLOUDFLARE_EMAIL,
    "X-Auth-Key": env.CLOUDFLARE_API_KEY,
    "Content-Type": "application/json"
  };

  try {
    // Make a GET request to the Cloudflare API to get the live input status.
    const apiResponse = await fetch(apiUrl, { headers });

    // If the API response is not OK, return an error response.
    if (!apiResponse.ok) {
      return new Response(
        JSON.stringify({ error: "Failed to fetch stream status from Cloudflare." }),
        { status: apiResponse.status, headers: { "Content-Type": "application/json" } }
      );
    }

    // Parse the JSON response from Cloudflare.
    const data = await apiResponse.json();

    // Cloudflare's API returns a JSON object with a "result" property.
    // For example, data.result.status might be "active" if the stream is receiving video,
    // or "idle" if it's not.
    const streamStatus = data.result && data.result.status ? data.result.status : "unknown";

    // Return the stream status to the client.
    return new Response(
      JSON.stringify({ status: streamStatus }),
      { headers: { "Content-Type": "application/json" } }
    );
  } catch (error) {
    // Catch and return any unexpected errors.
    return new Response(
      JSON.stringify({ error: "An error occurred while fetching the stream status.", details: error.message }),
      { status: 500, headers: { "Content-Type": "application/json" } }
    );
  }
}

// Listen for fetch events and pass the request along with the environment bindings.
addEventListener("fetch", event => {
  // The 'env' object contains our environment variables.
  event.respondWith(handleRequest(event.request, env));
});
