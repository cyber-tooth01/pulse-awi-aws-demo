#!/usr/bin/env python3
"""
Timestream query testing script
Tests Timestream connection and queries recent data
"""

import boto3
import sys
from datetime import datetime

AWS_REGION = "us-east-1"
DATABASE_NAME = "pulseaqi_demo"
TABLE_NAME = "sensor_data"

def test_timestream_query():
    """Test basic Timestream queries"""
    print("PulseAQI Timestream Test")
    print("=" * 60)
    print(f"Region:   {AWS_REGION}")
    print(f"Database: {DATABASE_NAME}")
    print(f"Table:    {TABLE_NAME}")
    print("=" * 60)
    
    try:
        # Initialize Timestream query client
        query_client = boto3.client('timestream-query', region_name=AWS_REGION)
        
        # Test 1: Count total records
        print("\n📊 Test 1: Count total records")
        query = f'SELECT COUNT(*) as total FROM "{DATABASE_NAME}"."{TABLE_NAME}"'
        response = query_client.query(QueryString=query)
        
        if response['Rows']:
            total = response['Rows'][0]['Data'][0]['ScalarValue']
            print(f"   Total records: {total}")
        
        # Test 2: Get latest records
        print("\n📊 Test 2: Latest 10 records")
        query = f'''
            SELECT time, node_id, dimension_metric, measure_value::double as value 
            FROM "{DATABASE_NAME}"."{TABLE_NAME}" 
            WHERE time > ago(1h)
            ORDER BY time DESC 
            LIMIT 10
        '''
        response = query_client.query(QueryString=query)
        
        if response['Rows']:
            print(f"   Found {len(response['Rows'])} recent records:")
            for row in response['Rows'][:5]:  # Show first 5
                data = row['Data']
                timestamp = data[0]['ScalarValue']
                node_id = data[1]['ScalarValue']
                metric = data[2]['ScalarValue']
                value = data[3]['ScalarValue']
                print(f"   {timestamp} | {node_id} | {metric}: {value}")
        else:
            print("   ⚠ No records found in the last hour")
        
        # Test 3: Get unique nodes
        print("\n📊 Test 3: Active nodes")
        query = f'''
            SELECT DISTINCT node_id 
            FROM "{DATABASE_NAME}"."{TABLE_NAME}" 
            WHERE time > ago(1h)
        '''
        response = query_client.query(QueryString=query)
        
        if response['Rows']:
            nodes = [row['Data'][0]['ScalarValue'] for row in response['Rows']]
            print(f"   Active nodes: {', '.join(nodes)}")
        else:
            print("   ⚠ No active nodes in the last hour")
        
        # Test 4: Latest AQI values
        print("\n📊 Test 4: Latest AQI by node")
        query = f'''
            SELECT node_id, MAX(measure_value::double) as latest_aqi 
            FROM "{DATABASE_NAME}"."{TABLE_NAME}" 
            WHERE measure_name = 'value' 
              AND dimension_metric = 'aqi' 
              AND time > ago(10m)
            GROUP BY node_id
        '''
        response = query_client.query(QueryString=query)
        
        if response['Rows']:
            for row in response['Rows']:
                node_id = row['Data'][0]['ScalarValue']
                aqi = row['Data'][1]['ScalarValue']
                print(f"   {node_id}: AQI {aqi}")
        else:
            print("   ⚠ No AQI data in the last 10 minutes")
        
        print("\n✅ All tests completed successfully!")
        
    except query_client.exceptions.ResourceNotFoundException:
        print(f"\n✗ Error: Database or table not found")
        print(f"   Make sure {DATABASE_NAME}.{TABLE_NAME} exists")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    test_timestream_query()
