from flask import Flask, request, jsonify
from flask_cors import CORS
import os, re
from difflib import SequenceMatcher

app = Flask(__name__)
CORS(app)

def normalize_sql(sql):
    return re.sub(r'\s+', ' ', sql.strip().lower())

def similar(a, b):
    return SequenceMatcher(None, a, b).ratio()

def read_php_files(root):
    php_files = []
    for dirpath, _, filenames in os.walk(root):
        for file in filenames:
            if file.endswith(".php"):
                php_files.append(os.path.join(dirpath, file))
    return php_files

def find_sql_occurrences(sql_input, codebase_root):
    norm_query = normalize_sql(sql_input)
    files = read_php_files(codebase_root)
    matches = []

    for file in files:
        with open(file, 'r', errors='ignore') as f:
            lines = f.readlines()

        for i, line in enumerate(lines):
            if 'select' in line.lower():
                line_clean = normalize_sql(line)
                sim = similar(norm_query, line_clean)
                if sim > 0.5:
                    matches.append({
                        "file": file,
                        "line": i + 1,
                        "code": line.strip(),
                        "similarity": sim
                    })

    return sorted(matches, key=lambda m: -m['similarity'])

def check_input_validation(file_path, line_number):
    validated = False
    lines = []
    try:
        with open(file_path, 'r') as f:
            lines = f.readlines()
    except:
        return False

    for i in range(max(0, line_number-10), line_number+5):
        if i >= len(lines):
            continue
        if 'validate' in lines[i] or 'FormRequest' in lines[i]:
            validated = True
            break

    return validated

def analyze_sql_issues(sql):
    sql = sql.lower()
    issues = []

    if 'select *' in sql:
        issues.append("Avoid SELECT * — only select necessary columns.")

    if ' join ' in sql and ' on ' not in sql:
        issues.append("JOIN without ON clause detected — may result in Cartesian product.")

    if 'where' in sql:
        fields = re.findall(r'where\s+(.*?)\s*(?:order by|group by|limit|$)', sql)
        if fields:
            conds = fields[0].split('and')
            for cond in conds:
                field = cond.split('=')[0].strip()
                if field and field != 'id':
                    issues.append(f"Ensure WHERE field '{field}' is indexed.")

    if 'limit' not in sql:
        issues.append("No LIMIT clause — may return huge result sets.")

    return issues

def suggest_improvements(query, input_validated, issues):
    suggestions = []

    if not input_validated:
        suggestions.append("Sanitize and validate user input with Laravel's `validate()` or `FormRequest`.")

    suggestions.extend(issues)

    if 'select *' in query.lower():
        suggestions.append("Refactor query to only fetch required fields, e.g., `select('id', 'name')`")

    suggestions.append("Consider caching repeated reads using Laravel Cache or Redis.")

    return suggestions

@app.route("/analyze", methods=["POST"])
def analyze():
    data = request.json
    query = data.get("sql")
    project_path = data.get("project_path")

    matches = find_sql_occurrences(query, project_path)
    if not matches:
        return jsonify({"found": False, "message": "No match found in codebase."})

    top = matches[0]
    validated = check_input_validation(top['file'], top['line'])
    issues = analyze_sql_issues(query)
    suggestions = suggest_improvements(query, validated, issues)

    return jsonify({
        "found": True,
        "match": top,
        "validated": validated,
        "suggestions": suggestions
    })

if __name__ == "__main__":
    app.run(debug=True)
