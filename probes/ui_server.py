from pathlib import Path
import main
import uvicorn
main.setup_frontend(main.app, Path('/work/studio/frontend/dist'))
uvicorn.run(main.app, host='127.0.0.1', port=8010, log_level='warning')
