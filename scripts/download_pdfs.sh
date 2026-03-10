#!/bin/bash
GWS=~/.cargo/bin/gws
OUTPUT_DIR="$(pwd)/data/pdfs"
mkdir -p "$OUTPUT_DIR"

download_pdfs_from_folder() {
    local folder_id="$1"
    local folder_name="$2"
    local target="$OUTPUT_DIR/$folder_name"
    mkdir -p "$target"

    echo "=== Downloading from: $folder_name ==="
    files=$($GWS drive files list --params "{\"q\":\"\\\"$folder_id\\\" in parents\",\"fields\":\"files(id,name,mimeType)\"}" 2>/dev/null)

    echo "$files" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for f in data.get('files', []):
    if f['mimeType'] == 'application/pdf':
        print(f['id'] + '|' + f['name'])
" | while IFS='|' read -r file_id file_name; do
        echo "  Downloading: $file_name"
        $GWS drive files get --params "{\"fileId\":\"$file_id\",\"alt\":\"media\"}" > "$target/$file_name" 2>/dev/null
    done
}

# 根目錄 PDFs
download_pdfs_from_folder "1QutCz68R8-7UX2tPD7AzRI5zxAg0msiG" "root"

# 子資料夾 (these have subfolders, need to recurse into them to find PDFs)
download_pdfs_from_folder "1TokCwX9hL-pzvAdr9Se8EmADZusp00V4" "大群資料2"
download_pdfs_from_folder "1SorRdJ2-rukJGnfzOImbeEqmVf2GTXTk" "大群資料1"
download_pdfs_from_folder "1xkPWd4nvZ8ch6bVyYuhxQLPDjrkPxDnM" "第二組資料"

echo "=== Download complete ==="
ls -la "$OUTPUT_DIR"/*
