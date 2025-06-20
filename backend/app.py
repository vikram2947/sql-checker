from flask import Flask, request, jsonify
from flask_cors import CORS
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
import os
import re
import pickle
from difflib import SequenceMatcher

app = Flask(__name__)
CORS(app)

model = SentenceTransformer('all-MiniLM-L6-v2')
indexed_lines = []
CACHE_FILE = 'embedding_cache.pkl'
DEFAULT_PROJECT_PATH = "/absolute/path/to/laravel"
SCAN_SUBDIR = "app"  # Only scan the Laravel app directory

def normalize_sql(sql):
    return re.sub(r'\s+', ' ', sql.strip().lower())

def similar(a, b):
    return SequenceMatcher(None, a, b).ratio()

def classify_query(code_line):
    line_lower = code_line.lower()
    
    # Raw SQL queries
    if "db::select" in line_lower or "db::statement" in line_lower:
        return "Raw SQL (High Performance Risk)"
    elif "db::raw" in line_lower:
        return "Raw SQL with DB::raw (High Performance Risk)"
    
    # Query Builder
    elif "db::table" in line_lower:
        return "Query Builder (Moderate Performance Risk)"
    elif "db::connection" in line_lower:
        return "Query Builder with Custom Connection"
    
    # Eloquent ORM
    elif "->where" in line_lower and "::" in line_lower:
        return "Eloquent ORM (Lower Performance Risk)"
    elif "->get()" in line_lower:
        return "Eloquent Collection (Memory Intensive)"
    elif "->paginate" in line_lower:
        return "Eloquent Pagination (Good Performance)"
    elif "->chunk" in line_lower:
        return "Eloquent Chunking (Good for Large Datasets)"
    
    # Specific query patterns
    elif "->with(" in line_lower:
        return "Eloquent Eager Loading (Good Performance)"
    elif "->load(" in line_lower:
        return "Eloquent Lazy Loading (Potential N+1)"
    elif "->join(" in line_lower:
        return "Eloquent Join (Moderate Performance Risk)"
    elif "->leftjoin(" in line_lower:
        return "Eloquent Left Join (Moderate Performance Risk)"
    
    # Aggregation queries
    elif "->count(" in line_lower:
        return "Eloquent Count (Good Performance)"
    elif "->sum(" in line_lower or "->avg(" in line_lower:
        return "Eloquent Aggregation (Good Performance)"
    
    # Complex queries
    elif "->wherehas(" in line_lower:
        return "Eloquent WhereHas (Potential Performance Issue)"
    elif "->wheredoesnthave(" in line_lower:
        return "Eloquent WhereDoesntHave (Potential Performance Issue)"
    
    else:
        return "Unknown Query Type"

def check_input_validation(file_path, line_number):
    validated = False
    validation_methods = []
    security_issues = []
    lines = []
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except Exception as e:
        return False, [], []
    
    # Check surrounding context (20 lines before and after)
    start_line = max(0, line_number - 20)
    end_line = min(len(lines), line_number + 20)
    
    for i in range(start_line, end_line):
        line = lines[i].strip().lower()
        
        # Laravel validation patterns
        validation_patterns = [
            r'validate\(',  # Basic validation
            r'formrequest',  # Form Request validation
            r'request->validate',  # Request validation
            r'validator::make',  # Validator facade
            r'->rules\(',  # Validation rules
            r'->messages\(',  # Custom messages
        ]
        
        for pattern in validation_patterns:
            if re.search(pattern, line):
                validated = True
                validation_methods.append(f"Line {i+1}: {lines[i].strip()}")
        
        # Security patterns
        security_patterns = [
            r'escape\(',  # HTML escaping
            r'htmlspecialchars',  # PHP escaping
            r'strip_tags',  # Tag removal
            r'filter_var',  # PHP filtering
            r'preg_replace',  # Regex cleaning
        ]
        
        for pattern in security_patterns:
            if re.search(pattern, line):
                validation_methods.append(f"Line {i+1}: Security - {lines[i].strip()}")
        
        # Potential security issues
        if any(keyword in line for keyword in ['$_get', '$_post', '$_request']):
            if not any(secure in line for secure in ['validate', 'escape', 'filter']):
                security_issues.append(f"Line {i+1}: Direct superglobal access without validation")
    
    return validated, validation_methods, security_issues

def analyze_sql_issues(sql):
    sql = sql.lower()
    issues = []
    
    # Normalize SQL for better analysis
    normalized_sql = re.sub(r'\s+', ' ', sql.strip())
    
    # 1. SELECT * issues
    if 'select *' in normalized_sql:
        issues.append("🚨 Avoid SELECT * — only select necessary columns to reduce data transfer and improve performance.")
    
    # 2. Missing LIMIT clause
    if 'limit' not in normalized_sql and ('select' in normalized_sql or 'union' in normalized_sql):
        issues.append("⚠️ No LIMIT clause — may return huge result sets. Add LIMIT for pagination.")
    
    # 3. JOIN analysis
    if ' join ' in normalized_sql:
        if ' on ' not in normalized_sql:
            issues.append("🚨 JOIN without ON clause detected — may result in Cartesian product.")
        else:
            # Extract JOIN conditions for index recommendations
            join_conditions = re.findall(r'join\s+\w+\s+on\s+(.*?)(?:\s+where|\s+group|\s+order|\s+limit|$)', normalized_sql)
            for condition in join_conditions:
                fields = re.findall(r'(\w+)\.(\w+)\s*=\s*\w+\.\w+', condition)
                for table, field in fields:
                    issues.append(f"📊 Ensure JOIN field '{table}.{field}' is indexed for optimal performance.")
    
    # 4. WHERE clause analysis
    if 'where' in normalized_sql:
        # Extract WHERE conditions
        where_match = re.search(r'where\s+(.*?)(?:\s+group|\s+order|\s+limit|$)', normalized_sql)
        if where_match:
            where_clause = where_match.group(1)
            # Find field comparisons
            field_patterns = [
                r'(\w+)\s*=\s*\?',  # Parameterized queries
                r'(\w+)\s*=\s*[\'"]?\w+[\'"]?',  # Direct value comparisons
                r'(\w+)\s*in\s*\(',  # IN clauses
                r'(\w+)\s*like\s*[\'"]',  # LIKE clauses
            ]
            
            for pattern in field_patterns:
                fields = re.findall(pattern, where_clause)
                for field in fields:
                    if field not in ['id', 'created_at', 'updated_at']:
                        issues.append(f"📊 Ensure WHERE field '{field}' is indexed for optimal filtering.")
    
    # 5. Subquery analysis
    if '(' in normalized_sql and 'select' in normalized_sql:
        subqueries = re.findall(r'\(\s*select\s+.*?\)', normalized_sql, re.IGNORECASE | re.DOTALL)
        if len(subqueries) > 2:
            issues.append("⚠️ Multiple subqueries detected — consider using JOINs or EXISTS for better performance.")
    
    # 6. ORDER BY without LIMIT
    if 'order by' in normalized_sql and 'limit' not in normalized_sql:
        issues.append("⚠️ ORDER BY without LIMIT — sorting large datasets can be expensive.")
    
    # 7. GROUP BY analysis
    if 'group by' in normalized_sql:
        if 'having' not in normalized_sql:
            issues.append("💡 Consider adding HAVING clause if you need to filter grouped results.")
    
    # 8. DISTINCT usage
    if 'distinct' in normalized_sql:
        issues.append("💡 DISTINCT can be expensive on large datasets — ensure it's necessary.")
    
    # 9. UNION analysis
    if 'union' in normalized_sql:
        issues.append("💡 UNION operations can be expensive — consider if UNION ALL would suffice.")
    
    # 10. LIKE with leading wildcard
    like_patterns = re.findall(r'like\s+[\'"]%(\w+)', normalized_sql)
    if like_patterns:
        issues.append("🚨 LIKE with leading wildcard detected — this prevents index usage. Consider full-text search.")
    
    return issues

def suggest_improvements(query, input_validated, issues, validation_methods=None, security_issues=None):
    suggestions = []
    
    # Input validation suggestions
    if not input_validated:
        suggestions.append("🔐 **Security**: Implement Laravel validation using `$request->validate()` or FormRequest classes.")
        suggestions.append("🔐 **Security**: Use Laravel's built-in CSRF protection and input sanitization.")
    
    # Add specific validation methods found
    if validation_methods:
        suggestions.append("✅ **Validation Found**: " + ", ".join(validation_methods[:3]))
    
    # Add security issues found
    if security_issues:
        suggestions.append("🚨 **Security Issues**: " + ", ".join(security_issues[:3]))
    
    # SQL-specific improvements
    suggestions.extend(issues)
    
    # Laravel-specific optimizations
    query_lower = query.lower()
    
    if 'select *' in query_lower:
        suggestions.append("📊 **Performance**: Replace SELECT * with specific columns using `select('id', 'name', 'email')`")
        suggestions.append("📊 **Performance**: Use Eloquent's `select()` method for better type safety")
    
    if 'join' in query_lower:
        suggestions.append("🔗 **Joins**: Consider using Eloquent relationships instead of manual JOINs")
        suggestions.append("🔗 **Joins**: Use `with()` for eager loading to avoid N+1 queries")
    
    if 'where' in query_lower and 'limit' not in query_lower:
        suggestions.append("📄 **Pagination**: Implement pagination using `paginate()` or `simplePaginate()`")
        suggestions.append("📄 **Pagination**: For large datasets, use `chunk()` for memory efficiency")
    
    if 'order by' in query_lower:
        suggestions.append("📈 **Sorting**: Ensure ORDER BY columns are indexed")
        suggestions.append("📈 **Sorting**: Consider using database indexes for frequently sorted columns")
    
    # Caching suggestions
    suggestions.append("💾 **Caching**: Implement Redis caching for frequently accessed data")
    suggestions.append("💾 **Caching**: Use Laravel's `remember()` method for query result caching")
    
    # Database optimization
    suggestions.append("🗄️ **Database**: Run `EXPLAIN` on your query to analyze execution plan")
    suggestions.append("🗄️ **Database**: Consider adding composite indexes for multi-column WHERE clauses")
    
    # Code-level optimizations
    suggestions.append("⚡ **Code**: Use Eloquent's `lazy()` for large result sets")
    suggestions.append("⚡ **Code**: Implement database query logging in development")
    suggestions.append("⚡ **Code**: Use Laravel Telescope for query monitoring in development")
    
    return suggestions

def save_cache(data, path=CACHE_FILE):
    with open(path, 'wb') as f:
        pickle.dump(data, f)

def load_cache(path=CACHE_FILE):
    if os.path.exists(path):
        with open(path, 'rb') as f:
            return pickle.load(f)
    return None

def index_codebase(path, max_files=100):
    """Index codebase with limits and progress tracking"""
    code_lines = []
    scan_path = os.path.join(path, SCAN_SUBDIR)
    files_processed = 0
    
    print(f"Scanning path: {scan_path}")
    
    if not os.path.exists(scan_path):
        print(f"Warning: {scan_path} does not exist, scanning root path: {path}")
        scan_path = path
    
    for root, dirs, files in os.walk(scan_path):
        # Skip common non-essential directories
        dirs[:] = [d for d in dirs if d not in ['vendor', 'node_modules', '.git', 'storage', 'bootstrap/cache']]
        
        for fname in files:
            if fname.endswith(".php") and files_processed < max_files:
                fpath = os.path.join(root, fname)
                try:
                    with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                        lines = f.readlines()
                    
                    for i, line in enumerate(lines):
                        line = line.strip()
                        # More specific SQL pattern matching
                        sql_patterns = [
                            'db::select', 'db::statement', 'db::raw', 'db::table',
                            '->where(', '->join(', '->leftjoin(', '->rightjoin(',
                            '->select(', '->get()', '->first()', '->find(',
                            '->with(', '->load(', '->paginate(', '->chunk(',
                            'select ', 'insert ', 'update ', 'delete '
                        ]
                        
                        if line and any(pattern in line.lower() for pattern in sql_patterns):
                            code_lines.append({
                                "file": fpath,
                                "line": i + 1,
                                "text": line
                            })
                    
                    files_processed += 1
                    if files_processed % 10 == 0:
                        print(f"Processed {files_processed} files, found {len(code_lines)} SQL lines")
                        
                except Exception as e:
                    print(f"Error reading {fpath}: {e}")
                    continue
    
    print(f"Indexing complete: {files_processed} files processed, {len(code_lines)} SQL lines found")
    return code_lines

@app.route("/embed", methods=["POST"])
def embed_codebase():
    global indexed_lines
    user_path = request.json.get("project_path")
    if not user_path or not os.path.exists(user_path):
        return jsonify({"error": "Invalid Laravel path"}), 400

    print(f"Starting codebase indexing for: {user_path}")
    lines = index_codebase(user_path)
    
    if not lines:
        return jsonify({"error": "No SQL-related code found in the specified path"}), 400
    
    print(f"Starting embedding generation for {len(lines)} lines")
    texts = [entry["text"] for entry in lines]
    
    # Process embeddings in batches to avoid memory issues
    batch_size = 50
    all_embeddings = []
    
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        print(f"Processing embedding batch {i//batch_size + 1}/{(len(texts)-1)//batch_size + 1}")
        batch_embeddings = model.encode(batch)
        all_embeddings.extend(batch_embeddings)
    
    indexed_lines = [dict(entry, embedding=emb) for entry, emb in zip(lines, all_embeddings)]
    save_cache(indexed_lines)
    
    print(f"Embedding complete: {len(indexed_lines)} lines indexed")
    return jsonify({"status": "Indexed", "count": len(indexed_lines)})

@app.route("/analyze", methods=["POST"])
def analyze():
    global indexed_lines
    data = request.json
    query = data.get("sql")
    if not query:
        return jsonify({"error": "Query required"}), 400

    if not indexed_lines:
        cached = load_cache()
        if cached:
            indexed_lines = cached
        else:
            return jsonify({"error": "Codebase not indexed yet."}), 400

    query_embedding = model.encode([query])[0]
    similarities = cosine_similarity([query_embedding], [l["embedding"] for l in indexed_lines])[0]

    top_idx = similarities.argmax()
    top = indexed_lines[top_idx]
    similarity_score = float(similarities[top_idx])

    validated, validation_methods, security_issues = check_input_validation(top['file'], top['line'])
    issues = analyze_sql_issues(query)
    suggestions = suggest_improvements(query, validated, issues, validation_methods, security_issues)
    
    # Calculate performance score
    performance_score = calculate_performance_score(query, issues, validated)
    performance_rating = get_performance_rating(performance_score)

    return jsonify({
        "found": True,
        "match": {
            "file": top["file"],
            "line": top["line"],
            "code": top["text"],
            "similarity": similarity_score,
            "query_type": classify_query(top["text"])
        },
        "validated": validated,
        "validation_methods": validation_methods,
        "security_issues": security_issues,
        "suggestions": suggestions,
        "performance_score": performance_score,
        "performance_rating": performance_rating
    })

def calculate_performance_score(sql, issues, validated):
    """Calculate a performance score from 0-100 (100 being optimal)"""
    score = 100
    sql_lower = sql.lower()
    
    # Major performance issues (-20 points each)
    if 'select *' in sql_lower:
        score -= 20
    if ' join ' in sql_lower and ' on ' not in sql_lower:
        score -= 20
    if 'limit' not in sql_lower and ('select' in sql_lower or 'union' in sql_lower):
        score -= 15
    
    # Moderate performance issues (-10 points each)
    if 'like' in sql_lower and '%' in sql:
        score -= 10
    if 'distinct' in sql_lower:
        score -= 10
    if 'union' in sql_lower:
        score -= 10
    if 'order by' in sql_lower and 'limit' not in sql_lower:
        score -= 10
    
    # Minor performance issues (-5 points each)
    if len(issues) > 3:
        score -= 5
    if not validated:
        score -= 5
    
    # Bonus points for good practices (+5 points each)
    if 'limit' in sql_lower:
        score += 5
    if 'index' in sql_lower:
        score += 5
    if 'explain' in sql_lower:
        score += 5
    
    return max(0, min(100, score))

def get_performance_rating(score):
    """Convert score to performance rating"""
    if score >= 90:
        return "🟢 Excellent"
    elif score >= 75:
        return "🟡 Good"
    elif score >= 60:
        return "🟠 Fair"
    elif score >= 40:
        return "🔴 Poor"
    else:
        return "🔴 Critical"

if __name__ == "__main__":
    app.run(debug=True)