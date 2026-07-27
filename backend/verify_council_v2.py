"""verify_council_v2.py

CLI or HTTP client tool to verify the council session API.
"""

import argparse
import sys
import traceback
import math
import logging
from typing import Optional
import requests

logger = logging.getLogger(__name__)

def _get_exception_location(tb) -> tuple[str, str]:
    import os
    try:
        if not tb:
            return "unknown", "unknown"
        curr_tb = tb
        target_tb = tb
        visited = set()
        current_file = os.path.basename(__file__) if "__file__" in globals() else "verify_council_v2.py"
        while curr_tb:
            tb_id = id(curr_tb)
            if tb_id in visited:
                break
            visited.add(tb_id)
            if len(visited) > 100:
                break
            frame = getattr(curr_tb, "tb_frame", None)
            if frame:
                f_code = getattr(frame, "f_code", None)
                if f_code:
                    co_filename = getattr(f_code, "co_filename", None)
                    if co_filename and isinstance(co_filename, str) and current_file in os.path.basename(co_filename):
                        target_tb = curr_tb
            curr_tb = getattr(curr_tb, "tb_next", None)
        
        frame = getattr(target_tb, "tb_frame", None)
        if not frame:
            return "unknown", "unknown"
        f_code = getattr(frame, "f_code", None)
        if not f_code:
            return "unknown", "unknown"
        co_filename = getattr(f_code, "co_filename", None)
        file_name = os.path.basename(co_filename) if co_filename and isinstance(co_filename, str) else "unknown"
        line_no = str(getattr(target_tb, "tb_lineno", "unknown"))
        return file_name, line_no
    except Exception as e:  # Safety net for traversing potentially corrupted tracebacks
        logger.warning(f"Error traversing traceback: {e}")
        return "unknown", "unknown"

def _handle_exception(e: Exception, error_type_name: str, debug: bool) -> None:
    file_name, line_no = _get_exception_location(e.__traceback__)
    print(f"❌ {error_type_name} at {file_name}:{line_no}: {e}")
    logger.error(f"{error_type_name} at {file_name}:{line_no}: {e}", exc_info=True)
    if debug:
        traceback.print_exc()

def _process_response(response: requests.Response) -> bool:
    if response.status_code == 204:
        data = {}
    else:
        try:
            data = response.json()
        except ValueError as e:
            print(f"❌ Error: Failed to decode JSON: {e}")
            logger.error(f"Failed to decode JSON: {e}")
            return False
        except requests.exceptions.RequestException as e:
            print(f"❌ Error: Failed to read response content: {e}")
            logger.error(f"Failed to read response content: {e}")
            return False

    if not isinstance(data, dict):
        data_str = str(data)
        if len(data_str) > 200:
            data_str = data_str[:200] + "... (truncated)"
        print(f"❌ Error: Response JSON is not a dictionary (received type: {type(data).__name__})")
        logger.error(f"Response JSON is not a dictionary: {data_str}")
        return False

    session_id = data.get('session_id')
    if session_id is not None and not isinstance(session_id, str):
        print(f"❌ Error: 'session_id' field is not a string (received type: {type(session_id).__name__})")
        logger.error(f"'session_id' field is not a string (received type: {type(session_id).__name__})")
        return False

    synthesis = data.get('synthesis')
    if synthesis is None:
        synthesis = ""
    elif not isinstance(synthesis, str):
        print(f"❌ Error: 'synthesis' field is not a string (received type: {type(synthesis).__name__})")
        logger.error(f"'synthesis' field is not a string (received type: {type(synthesis).__name__})")
        return False

    debate_flow = data.get('debate_flow')
    if debate_flow is None:
        debate_flow = []
    elif not isinstance(debate_flow, list):
        print(f"❌ Error: 'debate_flow' field is not a list (received type: {type(debate_flow).__name__})")
        logger.error(f"'debate_flow' field is not a list (received type: {type(debate_flow).__name__})")
        return False

    print("✅ Success!")
    print(f"Session ID: {data.get('session_id')}")
    if len(synthesis) > 200:
        print(f"Synthesis: {synthesis[:200]}...")
    else:
        print(f"Synthesis: {synthesis}")
    print(f"Debate Flow: {len(debate_flow)} responses received.")
    for i, entry in enumerate(debate_flow):
        if not isinstance(entry, dict):
            print(f"❌ Error: debate_flow entry at index {i} is not a dictionary (received type: {type(entry).__name__})")
            logger.error(f"debate_flow entry at index {i} is not a dictionary (received type: {type(entry).__name__})")
            return False
        
        agent = entry.get('agent')
        summary = entry.get('summary')
        
        if agent is None:
            print(f"❌ Error: debate_flow entry at index {i} is missing 'agent' key")
            logger.error(f"debate_flow entry at index {i} is missing 'agent' key")
            return False
        if not isinstance(agent, str):
            print(f"❌ Error: debate_flow entry at index {i} 'agent' is not a string (received type: {type(agent).__name__})")
            logger.error(f"debate_flow entry at index {i} 'agent' is not a string (received type: {type(agent).__name__})")
            return False
            
        if summary is None:
            print(f"❌ Error: debate_flow entry at index {i} is missing 'summary' key")
            logger.error(f"debate_flow entry at index {i} is missing 'summary' key")
            return False
        if not isinstance(summary, str):
            print(f"❌ Error: debate_flow entry at index {i} 'summary' is not a string (received type: {type(summary).__name__})")
            logger.error(f"debate_flow entry at index {i} 'summary' is not a string (received type: {type(summary).__name__})")
            return False
            
        print(f"  [{i}] {agent}: {summary}")
    return True

def verify_council_session(
    url: str,
    query: str,
    timeout: Optional[float] = 30.0,
    use_session: bool = False,
    debug: bool = False,
    send_as_json: bool = False
) -> bool:
    """Send a query to the council session API and print the result.

    Args:
        url: The API endpoint URL.
        query: The debate query.
        timeout: Request timeout in seconds.
        use_session: Whether to use requests.Session for the request.
        debug: Enable debug mode.
        send_as_json: Send query as JSON body instead of query parameters.

    Returns:
        True if the request was successful, False otherwise.
    """
    if not isinstance(url, str):
        print("❌ Error: URL must be a string")
        logger.error("URL must be a string")
        return False
    if not isinstance(query, str):
        print("❌ Error: Query must be a string")
        logger.error("Query must be a string")
        return False
    if not isinstance(use_session, bool):
        print("❌ Error: use_session must be a boolean")
        logger.error("use_session must be a boolean")
        return False
    if not isinstance(debug, bool):
        print("❌ Error: debug must be a boolean")
        logger.error("debug must be a boolean")
        return False
    if not isinstance(send_as_json, bool):
        print("❌ Error: send_as_json must be a boolean")
        logger.error("send_as_json must be a boolean")
        return False

    if not url or not url.strip():
        print("❌ Error: URL cannot be empty")
        logger.error("URL cannot be empty")
        return False
    if not query or not query.strip():
        print("❌ Error: Query cannot be empty")
        logger.error("Query cannot be empty")
        return False

    print(f"📡 Sending request to {url}...")
    if timeout is not None:
        if isinstance(timeout, tuple):
            if len(timeout) != 2:
                print("❌ Error: Timeout tuple must contain exactly 2 elements (connect, read)")
                logger.error("Timeout tuple must contain exactly 2 elements (connect, read)")
                return False
            resolved_timeout = []
            for t in timeout:
                if isinstance(t, bool):
                    print("❌ Error: Timeout elements must be positive numbers")
                    logger.error("Timeout elements must be positive numbers")
                    return False
                try:
                    t_val = float(t)
                except (ValueError, TypeError):
                    print("❌ Error: Timeout elements must be positive numbers")
                    logger.error("Timeout elements must be positive numbers")
                    return False
                if math.isnan(t_val) or math.isinf(t_val) or t_val <= 0:
                    print("❌ Error: Timeout elements must be positive numbers")
                    logger.error("Timeout elements must be positive numbers")
                    return False
                resolved_timeout.append(t_val)
            timeout = tuple(resolved_timeout)
        else:
            if isinstance(timeout, bool):
                print("❌ Error: Timeout must be a positive number")
                logger.error("Timeout must be a positive number")
                return False
            try:
                timeout_val = float(timeout)
            except (ValueError, TypeError):
                print("❌ Error: Timeout must be a positive number")
                logger.error("Timeout must be a positive number")
                return False
            if math.isnan(timeout_val) or math.isinf(timeout_val) or timeout_val <= 0:
                print("❌ Error: Timeout must be a positive number")
                logger.error("Timeout must be a positive number")
                return False
            timeout = timeout_val
    try:
        kwargs = {}
        if send_as_json:
            kwargs["json"] = {"query": query}
        else:
            kwargs["params"] = {"query": query}

        response = None
        try:
            if use_session:
                with requests.Session() as client:
                    response = client.post(url, timeout=timeout, **kwargs)
                    response.raise_for_status()
                    return _process_response(response)
            else:
                response = requests.post(url, timeout=timeout, **kwargs)
                response.raise_for_status()
                return _process_response(response)
        finally:
            if response is not None and hasattr(response, "close"):
                response.close()
    except requests.exceptions.MissingSchema as e:
        print(f"❌ URL Error: Missing schema in URL: {e}")
        logger.error(f"Missing schema in URL: {e}")
        return False
    except requests.exceptions.InvalidSchema as e:
        print(f"❌ URL Error: Invalid schema in URL: {e}")
        logger.error(f"Invalid schema in URL: {e}")
        return False
    except requests.exceptions.InvalidURL as e:
        print(f"❌ URL Error: Invalid URL format: {e}")
        logger.error(f"Invalid URL format: {e}")
        return False
    except requests.exceptions.Timeout as e:
        print(f"❌ Timeout Error: {e}")
        logger.error(f"Timeout Error: {e}")
        return False
    except requests.exceptions.SSLError as e:
        print(f"❌ SSL Error: SSL certificate verification failed: {e}")
        logger.error(f"SSL Error: SSL certificate verification failed: {e}")
        return False
    except requests.exceptions.ProxyError as e:
        print(f"❌ Proxy Error: Proxy connection failed: {e}")
        logger.error(f"Proxy Error: Proxy connection failed: {e}")
        return False
    except requests.exceptions.TooManyRedirects as e:
        print(f"❌ Redirect Error: Too many redirects: {e}")
        logger.error(f"Redirect Error: Too many redirects: {e}")
        return False
    except requests.exceptions.ContentDecodingError as e:
        print(f"❌ Content Decoding Error: Failed to decode response content: {e}")
        logger.error(f"Content Decoding Error: Failed to decode response content: {e}")
        return False
    except requests.exceptions.ChunkedEncodingError as e:
        print(f"❌ Chunked Encoding Error: Connection broken or incomplete chunk: {e}")
        logger.error(f"Chunked Encoding Error: Connection broken or incomplete chunk: {e}")
        return False
    except requests.exceptions.ConnectionError as e:
        print(f"❌ Connection Error: {e}")
        logger.error(f"Connection Error: {e}")
        return False
    except requests.exceptions.HTTPError as e:
        print(f"❌ HTTP Error: {e}")
        if e.response is not None:
            print(f"❌ Failed: {e.response.status_code}")
            try:
                text = e.response.text
            except (AttributeError, ValueError, LookupError, requests.exceptions.RequestException) as text_err:
                text = f"<Failed to read response text: {text_err}>"
            if text:
                if len(text) > 500:
                    print(text[:500] + "\n... (truncated)")
                else:
                    print(text)
        logger.error(f"HTTP Error: {e}")
        return False
    except requests.exceptions.RequestException as e:
        print(f"❌ Request Error: {e}")
        logger.error(f"Request Error: {e}")
        return False
    except TypeError as e:
        _handle_exception(e, "Type Error", debug)
        return False
    except ValueError as e:
        _handle_exception(e, "Value Error", debug)
        return False
    except AttributeError as e:
        _handle_exception(e, "Attribute Error", debug)
        return False
    except Exception as e:
        _handle_exception(e, f"Unexpected Error ({type(e).__name__})", debug)
        return False

def parse_timeout(value: str) -> Optional[float]:
    if value.lower() in ("none", "null"):
        return None
    try:
        val = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid timeout value: '{value}'")
    if math.isnan(val) or math.isinf(val) or val <= 0:
        raise argparse.ArgumentTypeError(f"Timeout must be a positive number: '{value}'")
    return val

def main() -> None:
    parser = argparse.ArgumentParser(description="Verify Council Session API")
    parser.add_argument(
        "--url",
        default="http://localhost:8000/api/council/session",
        help="API Endpoint URL"
    )
    parser.add_argument(
        "--query",
        default="最近の動画の視聴維持率を上げるための具体的な編集テクニックを教えてください。",
        help="Query for the council"
    )
    parser.add_argument(
        "--timeout",
        type=parse_timeout,
        default=30.0,
        help="Request timeout in seconds"
    )
    parser.add_argument(
        "--use-session",
        action="store_true",
        help="Use requests.Session for the request"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug mode with full traceback"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Send query as JSON body instead of query parameters"
    )

    args = parser.parse_args()
    success = verify_council_session(
        url=args.url,
        query=args.query,
        timeout=args.timeout,
        use_session=args.use_session,
        debug=args.debug,
        send_as_json=args.json
    )
    if not success:
        sys.exit(1)

if __name__ == "__main__":
    main()
