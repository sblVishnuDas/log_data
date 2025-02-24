import re
import os
import pandas as pd
from datetime import datetime, timedelta
from collections import defaultdict

def format_time_duration(seconds):
    """Format seconds as HH:MM:SS"""
    hours, remainder = divmod(int(seconds), 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

def analyze_log_file(log_file_path):
    # Regular expressions
    login_pattern = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) - (?:config) - INFO - Logging initialized for user: (.+) on (\d{4}-\d{2}-\d{2})")
    image_update_pattern = re.compile(r"Updated IMAGE_NUMBER to (\d+)_\d+ for all records of (\d+)")
    edit_pattern = re.compile(r"UPDATED (\w+) (.+) TO (.+) of (\d+)")
    r_num_pattern = re.compile(r"UPDATED r_num\s+TO (\d+) of (\d+)")
    doc_type_update_pattern = re.compile(r"Updated DOC_TYPE for (\d+) local records")
    any_update_pattern = re.compile(r"UPDATED")
    text_clipboard_pattern = re.compile(r"Text copied to clipboard: '(.+)'")
    ocr_image_pattern = re.compile(r"Updated IMAGE_NUMBER to (\d+)_00(\d+) for all records of (\d+)")
    shortcut_pattern = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} - scripts\.config - INFO - ([\w+]+) pressed")
    image_pattern_sheet5 = re.compile(r"Updated IMAGE_NUMBER to \d+_\d+ for all records of (\d+)")
    record_pattern_sheet5 = re.compile(r"of (\d+)$")
    
    # Enhanced OCR tracking patterns
    ocr_start_pattern = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) - scripts\.config - INFO - HWR mode set to True")
    ocr_end_pattern = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) - scripts\.config - DEBUG - Text copied to clipboard: '(.+)'")

    # Data storage
    sessions = []
    current_session = None
    ocr_records = {}
    shortcuts = {}
    image_record_map = defaultdict(set)
    current_image = None
    current_user = None
    current_date = None
    
    # OCR timing tracking with specific text criteria
    current_ocr_start_time = None
    current_ocr_image_id = None
    ocr_durations = defaultdict(list)
    ocr_durations_with_criteria = defaultdict(list)
    ocr_in_progress = False

    print(f"Opening log file: {log_file_path}")
    try:
        with open(log_file_path, "r", encoding="utf-8") as file:
            lines = file.readlines()
        print(f"Successfully loaded {len(lines)} log lines")
    except Exception as e:
        print(f"Error reading log file: {e}")
        return [], [], {}, []

    for i, line in enumerate(lines):
        # Track OCR start time
        ocr_start_match = ocr_start_pattern.search(line)
        if ocr_start_match:
            current_ocr_start_time = datetime.strptime(ocr_start_match.group(1), "%Y-%m-%d %H:%M:%S")
            ocr_in_progress = True
            print(f"OCR start detected at {current_ocr_start_time}")

        # Track OCR end time with specific text criteria
        ocr_end_match = ocr_end_pattern.search(line)
        if ocr_end_match and current_ocr_start_time and current_ocr_image_id and ocr_in_progress:
            end_time = datetime.strptime(ocr_end_match.group(1), "%Y-%m-%d %H:%M:%S")
            clipboard_text = ocr_end_match.group(2)
            
            # Calculate basic duration for all OCR operations
            duration = (end_time - current_ocr_start_time).total_seconds()
            ocr_durations[current_ocr_image_id].append(duration)
            
            # Apply specific criteria - check if text contains name parts
            words = clipboard_text.split()
            # Check if clipboard text contains space-separated words that might be names
            if len(words) >= 2:
                print(f"Name criteria matched in clipboard text: '{clipboard_text}'")
                ocr_durations_with_criteria[current_ocr_image_id].append({
                    'duration': duration,
                    'text': clipboard_text,
                    'start_time': current_ocr_start_time,
                    'end_time': end_time
                })
            
            ocr_in_progress = False
            current_ocr_start_time = None

        # First, check for login to update current user and date
        login_match = login_pattern.search(line)
        if login_match:
            current_user = login_match.group(2)
            current_date = login_match.group(3)
            print(f"Found login at line {i}: {line.strip()}")

            # Close previous session if exists
            if current_session:
                second_last_timestamp = None
                last_timestamp = None

                for j in range(i-1, -1, -1):
                    try:
                        if "- config - INFO - Logging initialized for user:" in lines[j]:
                            continue

                        timestamp_str = lines[j][:19]
                        current_timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")

                        if last_timestamp is None:
                            last_timestamp = current_timestamp
                        elif second_last_timestamp is None:
                            second_last_timestamp = current_timestamp
                            break
                    except (ValueError, IndexError):
                        continue

                end_time = second_last_timestamp if second_last_timestamp else last_timestamp
                if end_time:
                    duration_seconds = (end_time - current_session["start_time"]).total_seconds()
                    current_session["end_time"] = end_time
                    current_session["duration_minutes"] = round(duration_seconds / 60, 2)
                    current_session["duration_seconds"] = duration_seconds

                current_session["total_record_count"] = 0
                for image_id, r_nums in current_session["image_records"].items():
                    max_r_num = max(r_nums) if r_nums else 0
                    current_session["total_record_count"] += max_r_num

                if not current_session["images_processed_count"]:
                    current_session["images_processed_count"] = sum(1 for r_nums in current_session["image_records"].values() if r_nums)

                sessions.append(current_session)

            # Start new session
            timestamp = datetime.strptime(login_match.group(1), "%Y-%m-%d %H:%M:%S")
            current_session = {
                "user": current_user,
                "date": current_date,
                "start_time": timestamp,
                "end_time": None,
                "duration_minutes": 0,
                "duration_seconds": 0,
                "records": set(),
                "image_records": {},
                "update_count": 0,
                "character_count": 0,
                "column_edits": {},
                "images_processed_count": 0,
                "image_sections": {},
                "total_ocr_duration": 0,
                "total_name_ocr_duration": 0  # New field for criteria-based OCR
            }

        # Process Sheet 5 data
        image_match_sheet5 = image_pattern_sheet5.search(line)
        record_match_sheet5 = record_pattern_sheet5.search(line)

        if image_match_sheet5:
            current_image = image_match_sheet5.group(1)
        elif record_match_sheet5 and current_image:
            record_number = record_match_sheet5.group(1)
            image_record_map[current_image].add(record_number)

        # Track shortcuts
        shortcut_match = shortcut_pattern.search(line)
        if shortcut_match:
            shortcut = shortcut_match.group(1)
            shortcuts[shortcut] = shortcuts.get(shortcut, 0) + 1
            print(f"Tracked shortcut: {shortcut}")

        # Process OCR tracking
        ocr_image_match = ocr_image_pattern.search(line)
        if ocr_image_match:
            image_num = ocr_image_match.group(1)
            image_id = ocr_image_match.group(3)
            current_ocr_image_id = image_id
            if image_id not in ocr_records:
                ocr_records[image_id] = {
                    'image_number': f"{image_num}_{ocr_image_match.group(2)}",
                    'clipboard_count': 0,
                    'name_clipboard_count': 0,  # New field for criteria-based count
                    'user': current_user,
                    'date': current_date,
                    'ocr_durations': [],
                    'name_ocr_durations': []  # New field for criteria-based durations
                }

        clipboard_match = text_clipboard_pattern.search(line)
        if clipboard_match and current_ocr_image_id:
            ocr_records[current_ocr_image_id]['clipboard_count'] += 1
            clipboard_text = clipboard_match.group(1)
            
            # Check if clipboard text meets name criteria
            words = clipboard_text.split()
            if len(words) >= 2:
                ocr_records[current_ocr_image_id]['name_clipboard_count'] += 1

        # Track records by IMAGE_NUMBER updates
        image_match = image_update_pattern.search(line)
        if image_match and current_session:
            image_num = image_match.group(1)
            record_id = image_match.group(2)
            current_session["records"].add(record_id)
            if record_id not in current_session["image_records"]:
                current_session["image_records"][record_id] = set()

            current_session["image_sections"][record_id] = {
                "image_num": image_num,
                "records_processed": 0
            }

        # Track DOC_TYPE updates
        doc_type_match = doc_type_update_pattern.search(line)
        if doc_type_match and current_session:
            record_count = int(doc_type_match.group(1))
            current_session["images_processed_count"] = record_count

        # Track records by r_num updates
        r_num_match = r_num_pattern.search(line)
        if r_num_match and current_session:
            r_num = int(r_num_match.group(1))
            record_id = r_num_match.group(2)

            if record_id not in current_session["image_records"]:
                current_session["image_records"][record_id] = set()
            current_session["image_records"][record_id].add(r_num)

            if record_id in current_session["image_sections"]:
                current_section = current_session["image_sections"][record_id]
                current_section["records_processed"] = max(current_section["records_processed"], r_num)

        if current_session and any_update_pattern.search(line):
            current_session["update_count"] += 1

        edit_match = edit_pattern.search(line)
        if edit_match and current_session:
            column_name = edit_match.group(1)
            new_value = edit_match.group(3)
            record_id = edit_match.group(4)

            current_session["character_count"] += len(new_value)

            if column_name not in current_session["column_edits"]:
                current_session["column_edits"][column_name] = 0
            current_session["column_edits"][column_name] += 1

    # Handle the last session
    if current_session:
        second_last_timestamp = None
        last_timestamp = None

        for j in range(len(lines)-1, -1, -1):
            try:
                if "- config - INFO - Logging initialized for user:" in lines[j]:
                    continue

                timestamp_str = lines[j][:19]
                current_timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")

                if last_timestamp is None:
                    last_timestamp = current_timestamp
                elif second_last_timestamp is None:
                    second_last_timestamp = current_timestamp
                    break
            except (ValueError, IndexError):
                continue

        end_time = second_last_timestamp if second_last_timestamp else last_timestamp
        if end_time:
            duration_seconds = (end_time - current_session["start_time"]).total_seconds()
            current_session["end_time"] = end_time
            current_session["duration_minutes"] = round(duration_seconds / 60, 2)
            current_session["duration_seconds"] = duration_seconds

        current_session["total_record_count"] = 0
        for image_id, r_nums in current_session["image_records"].items():
            max_r_num = max(r_nums) if r_nums else 0
            current_session["total_record_count"] += max_r_num

        if not current_session["images_processed_count"]:
            current_session["images_processed_count"] = sum(1 for r_nums in current_session["image_records"].values() if r_nums)

        sessions.append(current_session)

    # Convert OCR records to list format with durations
    ocr_data = []
    total_ocr_duration = 0
    total_name_ocr_duration = 0
    
    for image_id, data in ocr_records.items():
        # Process standard OCR durations
        durations = ocr_durations.get(image_id, [])
        avg_duration = sum(durations) / len(durations) if durations else 0
        total_duration = sum(durations)
        total_ocr_duration += total_duration
        
        # Process name-specific OCR durations
        name_durations = [item['duration'] for item in ocr_durations_with_criteria.get(image_id, [])]
        name_avg_duration = sum(name_durations) / len(name_durations) if name_durations else 0
        name_total_duration = sum(name_durations)
        total_name_ocr_duration += name_total_duration
        
        # Add detailed entry for each name OCR operation
        for name_ocr in ocr_durations_with_criteria.get(image_id, []):
            ocr_data.append({
                'User': data['user'],
                'Date': data['date'],
                'Image ID': image_id,
                'Image Number': data['image_number'],
                'OCR Attempt': data['clipboard_count'],
                'OCR Duration': round(name_ocr['duration'], 2),
                'Total OCR Duration': round(name_ocr['duration'], 2),  # For name OCRs, individual duration = total
                'Start Time': name_ocr['start_time'].strftime("%H:%M:%S"),
                'End Time': name_ocr['end_time'].strftime("%H:%M:%S"),
                'Extracted Text': name_ocr['text'],
                'Is Name OCR': 'Yes',
                'Log File': os.path.basename(log_file_path)
            })
        
        # If no name OCRs were found for this image, still add the standard OCR entry
        if image_id not in ocr_durations_with_criteria:
            ocr_data.append({
                'User': data['user'],
                'Date': data['date'],
                'Image ID': image_id,
                'Image Number': data['image_number'],
                'OCR Attempt': data['clipboard_count'],
                'OCR Duration': round(avg_duration, 2),
                'Total OCR Duration': round(total_duration, 2),
                'Start Time': '',
                'End Time': '',
                'Extracted Text': '',
                'Is Name OCR': 'No',
                'Log File': os.path.basename(log_file_path)
            })

    # Convert shortcuts to list format with user and date
    shortcut_data = [
        {
            'User': sessions[0]["user"] if sessions else "N/A",
            'Date': sessions[0]["date"] if sessions else "N/A",
            'SHORTCUT_NAME': key,
            'SHORTCUT': value,
            'Log File': os.path.basename(log_file_path)
        }
        for key, value in shortcuts.items()
    ]

    # Process image record map for Sheet 5
    image_record_data = []
    for image, records in image_record_map.items():
        image_record_data.append({
            'User': current_user,
            'Date': current_date,
            'Image Processed': image,
            'Records Processed (Unique Count)': len(records),
            'Log File': os.path.basename(log_file_path)
        })

    # Add log file name and OCR duration to each session for tracking
    for session in sessions:
        session['log_file'] = os.path.basename(log_file_path)
        session['total_ocr_duration'] = total_ocr_duration
        session['total_name_ocr_duration'] = total_name_ocr_duration

    return sessions, ocr_data, shortcut_data, image_record_data

def create_excel_report(all_sessions, all_ocr_data, all_shortcut_data, all_image_record_data, output_path):
    print(f"Creating Excel report at: {output_path}")
    excel_data = []

    # Get all unique users
    unique_users = set(session["user"] for session in all_sessions)
    
    # Get all dates for date range calculation
    dates = [session["date"] for session in all_sessions if "date" in session]
    earliest_date = min(dates) if dates else "N/A"
    latest_date = max(dates) if dates else "N/A"

    for session in all_sessions:
        excel_data.append({
            "User": session["user"],
            "Date": session["date"],
            "Start Time": session["start_time"].strftime("%H:%M:%S"),
            "End Time": session["end_time"].strftime("%H:%M:%S") if session["end_time"] else "",
            "Duration (minutes)": session["duration_minutes"],
            "Total Images": len(session["records"]),
            "Update Count": session["update_count"],
            "Character Count": session["character_count"],
            "Log File": session["log_file"]
        })

    # Update OCR data format WITHOUT extracted text
    ocr_formatted_data = []
    for item in all_ocr_data:
        ocr_formatted_data.append({
            'User': item['User'],
            'Date': item['Date'],
            'Image ID': item['Image ID'],
            'Image Number': item['Image Number'],
            'OCR Attempt': item['OCR Attempt'],
            'Total OCR Duration': round(item['Total OCR Duration'], 2),
            'Start Time': item.get('Start Time', ''),
            'End Time': item.get('End Time', ''),
            'Is Name OCR': item.get('Is Name OCR', 'No'),
            'Log File': item['Log File']
        })

    # Calculate user-specific summaries for Sheet 3
    sheet3_data = []
    total_duration = 0
    total_ocr_duration = 0
    total_name_ocr_duration = 0
    
    for user in unique_users:
        user_sessions = [s for s in all_sessions if s["user"] == user]
        user_ocr_data = [o for o in all_ocr_data if o['User'] == user]
        user_shortcut_data = [s for s in all_shortcut_data if s['User'] == user]
        user_image_data = [i for i in all_image_record_data if i['User'] == user]
        
        # Calculate user date range
        user_dates = [s["date"] for s in user_sessions]
        earliest_user_date = min(user_dates) if user_dates else "N/A"
        latest_user_date = max(user_dates) if user_dates else "N/A"
        
        # Calculate total duration
        user_duration = sum(s["duration_seconds"] for s in user_sessions)
        total_duration += user_duration
        user_duration_formatted = format_time_duration(user_duration)
        
        # Calculate OCR metrics
        user_ocr_attempts = sum(o['OCR Attempt'] for o in user_ocr_data)
        user_ocr_duration = sum(o['Total OCR Duration'] for o in user_ocr_data)
        total_ocr_duration += user_ocr_duration
        
        # Calculate name OCR durations
        user_name_ocr_data = [o for o in user_ocr_data if o.get('Is Name OCR', 'No') == 'Yes']
        user_name_ocr_duration = sum(o['Total OCR Duration'] for o in user_name_ocr_data)
        total_name_ocr_duration += user_name_ocr_duration
        
        # Calculate other metrics
        user_image_count = len(set(o['Image ID'] for o in user_ocr_data))
        user_shortcuts = sum(s['SHORTCUT'] for s in user_shortcut_data)
        user_character_count = sum(s["character_count"] for s in user_sessions)
        user_images_processed = len(set(i['Image Processed'] for i in user_image_data))
        user_records_processed = sum(i['Records Processed (Unique Count)'] for i in user_image_data)
        
        sheet3_data.append({
            "Username": user,
            "Date Range": f"{earliest_user_date} to {latest_user_date}" if user_dates else "N/A",
            "Total Duration": user_duration_formatted,
            "Total OCR Attempts": user_ocr_attempts,
            "Total OCR Duration (seconds)": round(user_ocr_duration, 2),
            "Total OCR Duration (formatted)": format_time_duration(user_ocr_duration),
            "Total Name OCR Duration (seconds)": round(user_name_ocr_duration, 2),
            "Total Name OCR Duration (formatted)": format_time_duration(user_name_ocr_duration),
            "Total Images": user_image_count,
            "Total Shortcuts": user_shortcuts,
            "Total Character Count": user_character_count,
            "Total Images Processed": user_images_processed,
            "Total Records Processed": user_records_processed,
            "Log Files Processed": len(set(session["log_file"] for session in user_sessions))
        })

    # Add total row
    total_duration_formatted = format_time_duration(total_duration)
    sheet3_data.append({
        "Username": "Total (All Users)",
        "Date Range": f"{earliest_date} to {latest_date}" if dates else "N/A",
        "Total Duration": total_duration_formatted,
        "Total OCR Attempts": sum(item['OCR Attempt'] for item in all_ocr_data),
        "Total OCR Duration (seconds)": round(total_ocr_duration, 2),
        "Total OCR Duration (formatted)": format_time_duration(total_ocr_duration),
        "Total Name OCR Duration (seconds)": round(total_name_ocr_duration, 2),
        "Total Name OCR Duration (formatted)": format_time_duration(total_name_ocr_duration),
        "Total Images": len(set(item['Image ID'] for item in all_ocr_data)),
        "Total Shortcuts": sum(item['SHORTCUT'] for item in all_shortcut_data),
        "Total Character Count": sum(session["character_count"] for session in all_sessions),
        "Total Images Processed": len(set(item['Image Processed'] for item in all_image_record_data)),
        "Total Records Processed": sum(item['Records Processed (Unique Count)'] for item in all_image_record_data),
        "Log Files Processed": len(set(session["log_file"] for session in all_sessions))
    })

    # Convert to DataFrames
    df_sessions = pd.DataFrame(excel_data)
    df_ocr = pd.DataFrame(ocr_formatted_data)
    df_shortcuts = pd.DataFrame(all_shortcut_data)
    df_image_records = pd.DataFrame(all_image_record_data)
    df_summary = pd.DataFrame(sheet3_data)

    # Create unique output path with timestamp
    if output_path.endswith('.xlsx'):
        base_path = output_path[:-5]
        extension = '.xlsx'
    else:
        base_path = output_path
        extension = ''

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    unique_output_path = f"{base_path}_{timestamp}{extension}"

    try:
        with pd.ExcelWriter(unique_output_path, engine='openpyxl') as writer:
            # Write all sheets
            df_sessions.to_excel(writer, sheet_name='Session Summary', index=False)
            df_ocr.to_excel(writer, sheet_name='OCR Analysis', index=False)
            df_summary.to_excel(writer, sheet_name='Duration and OCR Summary', index=False)
            df_shortcuts.to_excel(writer, sheet_name='Shortcut Analysis', index=False)
            df_image_records.to_excel(writer, sheet_name='Image Record Processing', index=False)

            print("Wrote all sheets to Excel")
        
        print(f"Successfully wrote Excel file to {unique_output_path}")
        return unique_output_path
    except Exception as e:
        print(f"Error writing Excel file: {e}")
        raise

def process_log_folder(folder_path, output_excel_path):
    """Process all log files in the given folder and generate a single report"""
    print(f"Processing all log files in folder: {folder_path}")
    
    all_sessions = []
    all_ocr_data = []
    all_shortcut_data = []
    all_image_record_data = []
    
    log_count = 0
    
    # Process each log file in the folder
    for filename in os.listdir(folder_path):
        if filename.endswith('.log'):
            log_count += 1
            log_file_path = os.path.join(folder_path, filename)
            print(f"Processing log file {log_count}: {filename}")
            
            try:
                sessions, ocr_data, shortcut_data, image_record_data = analyze_log_file(log_file_path)
                
                all_sessions.extend(sessions)
                all_ocr_data.extend(ocr_data)
                all_shortcut_data.extend(shortcut_data)
                all_image_record_data.extend(image_record_data)
                
                print(f"Successfully analyzed {filename}: Found {len(sessions)} sessions")
            except Exception as e:
                print(f"Error processing log file {filename}: {e}")
    
    if log_count == 0:
        print("No log files found in the specified folder")
        return None
    
    print(f"Completed processing {log_count} log files")
    print(f"Total data collected: {len(all_sessions)} sessions, {len(all_ocr_data)} OCR records, {len(all_shortcut_data)} shortcuts")
    
    # Generate the report
    if all_sessions or all_ocr_data or all_shortcut_data:
        output_path = create_excel_report(
            all_sessions, all_ocr_data, all_shortcut_data, all_image_record_data, output_excel_path
        )
        return output_path
    else:
        print("No data found to analyze across all log files.")
        return None

if __name__ == "__main__":
    # Replace with your actual folder path containing log files
    log_folder_path = r"C:\Users\18262\Documents\New folder"
    output_excel_path = r"C:\Users\18262\Documents\LOWWT.xlsx"
    
    try:
        print("Starting log folder analysis...")
        output_path = process_log_folder(log_folder_path, output_excel_path)
        
        if output_path:
            print(f"Report successfully created and saved to {output_path}")
        else:
            print("Failed to generate report - no data found.")
    except Exception as e:
        print(f"ERROR: Script execution failed: {e}")
        import traceback
        traceback.print_exc()