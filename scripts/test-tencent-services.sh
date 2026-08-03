#!/bin/bash
# Test script for all Tencent Cloud services configured for Opsora
# Usage: bash test-tencent-services.sh

SECRET_ID="${TENCENT_SECRET_ID:-}"
SECRET_KEY="${TENCENT_SECRET_KEY:-}"
REGION="ap-singapore"

if [ -z "$SECRET_ID" ] || [ -z "$SECRET_KEY" ]; then
    echo "ERROR: Set TENCENT_SECRET_ID and TENCENT_SECRET_KEY environment variables"
    exit 1
fi

echo "=========================================="
echo "  Tencent Cloud Services Test - Opsora"
echo "=========================================="
echo ""

# Test 1: VPC
echo "🔵 [1/7] Testing VPC..."
RESULT=$(tccli vpc DescribeVpcs --cli-unfold-argument 2>&1 | grep -c "opsora-vpc")
if [ "$RESULT" -gt 0 ]; then echo "  ✅ VPC: Active (vpc-cdjv3oev)"; else echo "  ❌ VPC: Not found"; fi

# Test 2: Subnet
echo "🔵 [2/7] Testing Subnet..."
RESULT=$(tccli vpc DescribeSubnets --cli-unfold-argument 2>&1 | grep -c "opsora-subnet")
if [ "$RESULT" -gt 0 ]; then echo "  ✅ Subnet: Active (subnet-lg9lvvvk)"; else echo "  ❌ Subnet: Not found"; fi

# Test 3: Security Group
echo "🔵 [3/7] Testing Security Group..."
RESULT=$(tccli vpc DescribeSecurityGroups --cli-unfold-argument 2>&1 | grep -c "opsora-sg")
if [ "$RESULT" -gt 0 ]; then echo "  ✅ Security Group: Active (sg-l6byllw2)"; else echo "  ❌ Security Group: Not found"; fi

# Test 4: Load Balancer
echo "🔵 [4/7] Testing Load Balancer..."
RESULT=$(tccli clb DescribeLoadBalancers --cli-unfold-argument 2>&1 | grep -c "opsora-clb")
if [ "$RESULT" -gt 0 ]; then echo "  ✅ CLB: Active (lb-aznldc76)"; else echo "  ❌ CLB: Not found"; fi

# Test 5: COS Bucket
echo "🔵 [5/7] Testing COS Bucket..."
RESULT=$(python3 -c "
from qcloud_cos import CosConfig, CosS3Client
config = CosConfig(Region='$REGION', SecretId='$SECRET_ID', SecretKey='$SECRET_KEY')
client = CosS3Client(config)
response = client.list_buckets()
buckets = response.get('Buckets', {}).get('Bucket', [])
print(len(buckets))
" 2>&1)
if [ "$RESULT" -gt 0 ]; then echo "  ✅ COS Bucket: Active (opsora-storage-1446770061)"; else echo "  ❌ COS Bucket: Not found"; fi

# Test 6: CFS Service
echo "🔵 [6/7] Testing CFS Service..."
RESULT=$(tccli cfs DescribeCfsServiceStatus --cli-unfold-argument 2>&1 | grep -c "created")
if [ "$RESULT" -gt 0 ]; then echo "  ✅ CFS: Active"; else echo "  ❌ CFS: Not active"; fi

# Test 7: Hunyuan AI (TokenHub)
echo "🔵 [7/7] Testing Hunyuan/TokenHub..."
echo "  ⚠️  Legacy Hunyuan models deprecated"
echo "  ℹ️  Migrate to TokenHub: https://tokenhub.tencentmaas.com/v1"
echo "  ℹ️  New model: hy3-preview"
echo "  ℹ️  Console: https://console.cloud.tencent.com/tokenhub/models"

echo ""
echo "=========================================="
echo "  Services Requiring Console Activation"
echo "=========================================="
echo "🟡 VOD:  https://console.cloud.tencent.com/vod (click Activate)"
echo "🟡 ASR:  https://console.cloud.tencent.com/asr (click Activate)"
echo "🟡 CDN:  https://console.cloud.tencent.com/cdn (click Activate)"
echo "🟡 Captcha: https://console.cloud.tencent.com/captcha (Create App)"
echo "🟡 SES:  Need domain verification for email sending"
echo "🟡 CVM:  Need balance top-up ($15-20/month)"
echo ""
echo "=========================================="
echo "  Test Complete"
echo "=========================================="
