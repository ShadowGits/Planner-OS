import sys
import urllib.request
import json

def main():
    if len(sys.argv) < 3:
        sys.stderr.write("Usage: python cloud_proxy.py <url> <token>\n")
        sys.exit(1)
        
    url = sys.argv[1]
    token = sys.argv[2]
    
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
            
        req = urllib.request.Request(
            url,
            data=line.encode('utf-8'),
            headers={
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            }
        )
        
        try:
            with urllib.request.urlopen(req) as response:
                result = response.read().decode('utf-8')
                sys.stdout.write(result + '\n')
                sys.stdout.flush()
        except urllib.error.HTTPError as e:
            try:
                sys.stdout.write(e.read().decode('utf-8') + '\n')
                sys.stdout.flush()
            except:
                sys.stderr.write(f"HTTPError {e.code}: {e.reason}\n")
        except Exception as e:
            sys.stderr.write(f"Error forwarding request: {e}\n")

if __name__ == "__main__":
    main()
