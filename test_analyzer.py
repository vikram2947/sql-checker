#!/usr/bin/env python3
"""
SQL Query Analyzer Test Script
Demonstrates how to analyze slow SQL queries for performance issues
"""

import requests
import json
import time

# Test queries with different performance issues
test_queries = [
    {
        "name": "SELECT * Query (Bad Performance)",
        "sql": "SELECT * FROM orders WHERE company_id = 1",
        "expected_issues": ["SELECT *", "No LIMIT", "Indexing needed"]
    },
    {
        "name": "Missing JOIN conditions",
        "sql": "SELECT o.id, c.name FROM orders o JOIN customers c WHERE o.status = 'active'",
        "expected_issues": ["JOIN without ON", "Cartesian product"]
    },
    {
        "name": "Inefficient LIKE query",
        "sql": "SELECT * FROM users WHERE email LIKE '%@gmail.com' ORDER BY created_at",
        "expected_issues": ["Leading wildcard", "No LIMIT", "SELECT *"]
    },
    {
        "name": "Multiple subqueries",
        "sql": """SELECT * FROM orders WHERE customer_id IN (
                    SELECT id FROM customers WHERE city IN (
                        SELECT city FROM locations WHERE region = 'North'
                    )
                ) AND product_id IN (
                    SELECT id FROM products WHERE category = 'electronics'
                )""",
        "expected_issues": ["Multiple subqueries", "SELECT *", "No LIMIT"]
    },
    {
        "name": "Good query with optimizations",
        "sql": "SELECT id, customer_name, total FROM orders WHERE status = 'completed' AND created_at >= '2023-01-01' LIMIT 100",
        "expected_issues": []  # Should have fewer issues
    }
]

def test_embedding():
    """Test the embedding endpoint"""
    print("🔍 Testing codebase embedding...")
    
    embed_data = {
        "project_path": "/home/vikramkumar/dev-automation/MultiChannel_API"
    }
    
    try:
        response = requests.post(
            "http://localhost:5000/embed",
            json=embed_data,
            timeout=120  # 2 minutes timeout
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"✅ Embedding successful: {result['count']} SQL lines indexed")
            return True
        else:
            print(f"❌ Embedding failed: {response.json()}")
            return False
            
    except requests.exceptions.Timeout:
        print("⏰ Embedding timed out - this is normal for large codebases")
        return False
    except Exception as e:
        print(f"❌ Embedding error: {e}")
        return False

def analyze_query(query_data):
    """Analyze a single SQL query"""
    print(f"\n📊 Analyzing: {query_data['name']}")
    print(f"SQL: {query_data['sql']}")
    
    try:
        response = requests.post(
            "http://localhost:5000/analyze",
            json={"sql": query_data['sql']},
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            
            print(f"📄 File: {result['match']['file']}")
            print(f"📍 Line: {result['match']['line']}")
            print(f"💡 Query Type: {result['match']['query_type']}")
            print(f"🔐 Input Validated: {'✅' if result['validated'] else '❌'}")
            print(f"📊 Performance Score: {result['performance_score']}/100 - {result['performance_rating']}")
            
            if result.get('validation_methods'):
                print(f"✅ Validation Methods: {len(result['validation_methods'])} found")
            
            if result.get('security_issues'):
                print(f"🚨 Security Issues: {len(result['security_issues'])} found")
            
            print("🚀 Optimization Suggestions:")
            for i, suggestion in enumerate(result['suggestions'][:5], 1):
                print(f"   {i}. {suggestion}")
            
            return result
        else:
            print(f"❌ Analysis failed: {response.json()}")
            return None
            
    except Exception as e:
        print(f"❌ Analysis error: {e}")
        return None

def main():
    """Main test function"""
    print("🧠 SQL Query Analyzer - Comprehensive Test")
    print("=" * 50)
    
    # Test server connectivity
    try:
        response = requests.get("http://localhost:5000", timeout=5)
        print("❌ Server responded with 404 (expected - no root route)")
    except requests.exceptions.ConnectionError:
        print("❌ Server not running! Please start the Flask server first.")
        print("Run: python3 backend/app.py")
        return
    except:
        print("✅ Server is running")
    
    # Test embedding
    embedding_success = test_embedding()
    
    if not embedding_success:
        print("\n⚠️  Continuing with cached embeddings (if available)...")
    
    # Test query analysis
    print("\n" + "=" * 50)
    print("🔍 Testing SQL Query Analysis")
    print("=" * 50)
    
    results = []
    for query_data in test_queries:
        result = analyze_query(query_data)
        if result:
            results.append({
                'query': query_data,
                'result': result
            })
        time.sleep(1)  # Small delay between requests
    
    # Summary
    print("\n" + "=" * 50)
    print("📈 ANALYSIS SUMMARY")
    print("=" * 50)
    
    for analysis in results:
        query_name = analysis['query']['name']
        score = analysis['result']['performance_score']
        rating = analysis['result']['performance_rating']
        print(f"{query_name}: {score}/100 - {rating}")

if __name__ == "__main__":
    main() 