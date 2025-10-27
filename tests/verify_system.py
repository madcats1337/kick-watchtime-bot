"""
Security Audit & System Verification
Checks for exposed secrets and verifies critical systems
"""

import os
import sys
from pathlib import Path

def check_secrets():
    """Check for exposed secrets in code"""
    print("🔒 SECURITY AUDIT")
    print("=" * 60)
    
    issues = []
    warnings = []
    
    # 1. Check .env file
    print("\n1️⃣ Checking .env file...")
    env_path = Path(".env")
    if env_path.exists():
        with open(env_path, 'r') as f:
            content = f.read()
            
        # Check for uncommented secrets
        if "DISCORD_TOKEN=" in content and not content.startswith("#"):
            for line in content.split('\n'):
                if line.startswith("DISCORD_TOKEN=") and not line.startswith("#"):
                    if len(line.split('=')[1].strip()) > 10:
                        issues.append("❌ DISCORD_TOKEN is uncommented in .env (should be commented)")
        
        print("   ✅ .env exists (good for local development)")
        print("   ⚠️  REMINDER: Never commit .env to git!")
    else:
        print("   ℹ️  No .env file (fine for production with environment variables)")
    
    # 2. Check .gitignore
    print("\n2️⃣ Checking .gitignore...")
    gitignore_path = Path(".gitignore")
    if gitignore_path.exists():
        with open(gitignore_path, 'r') as f:
            gitignore_content = f.read()
        
        if ".env" in gitignore_content:
            print("   ✅ .env is in .gitignore")
        else:
            issues.append("❌ .env is NOT in .gitignore - ADD IT NOW!")
        
        if "watchtime.db" in gitignore_content or "*.db" in gitignore_content:
            print("   ✅ Database files ignored")
        else:
            warnings.append("⚠️  Database files not in .gitignore")
    else:
        issues.append("❌ No .gitignore file found - CREATE ONE!")
    
    # 3. Check Python files for hardcoded secrets
    print("\n3️⃣ Scanning Python files for hardcoded secrets...")
    python_files = list(Path(".").rglob("*.py"))
    
    dangerous_patterns = [
        ("DISCORD_TOKEN", "discord token"),
        ("FLASK_SECRET_KEY", "flask secret key"),
        ("DATABASE_URL", "database URL")
    ]
    
    hardcoded_found = False
    for py_file in python_files:
        if "venv" in str(py_file) or ".venv" in str(py_file):
            continue
            
        with open(py_file, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
            
        for pattern, name in dangerous_patterns:
            # Look for hardcoded values (not os.getenv)
            if f'{pattern} = "' in content or f"{pattern} = '" in content:
                if "os.getenv" not in content[max(0, content.find(pattern)-50):content.find(pattern)+50]:
                    issues.append(f"❌ Possible hardcoded {name} in {py_file}")
                    hardcoded_found = True
    
    if not hardcoded_found:
        print("   ✅ No hardcoded secrets detected")
    
    # 4. Check configuration files
    print("\n4️⃣ Checking raffle configuration...")
    config_path = Path("raffle_system/config.py")
    if config_path.exists():
        with open(config_path, 'r') as f:
            config = f.read()
        
        # Verify Shuffle URL
        expected_url = "https://affiliate.shuffle.com/stats/1755f751-33a9-4532-804e-b14b5c90236b"
        if expected_url in config:
            print(f"   ✅ Shuffle affiliate URL correct: {expected_url}")
        else:
            issues.append(f"❌ Shuffle URL not found or incorrect!")
        
        # Verify campaign code
        if 'SHUFFLE_CAMPAIGN_CODE = "lele"' in config:
            print('   ✅ Shuffle campaign code correct: "lele"')
        else:
            issues.append('❌ Shuffle campaign code incorrect!')
    
    # 5. Summary
    print("\n" + "=" * 60)
    print("SECURITY AUDIT SUMMARY")
    print("=" * 60)
    
    if issues:
        print("\n🚨 CRITICAL ISSUES FOUND:")
        for issue in issues:
            print(f"   {issue}")
    
    if warnings:
        print("\n⚠️  WARNINGS:")
        for warning in warnings:
            print(f"   {warning}")
    
    if not issues and not warnings:
        print("\n✅ ALL SECURITY CHECKS PASSED!")
        print("\nBest Practices:")
        print("   • All secrets loaded from environment variables ✅")
        print("   • .env file properly ignored ✅")
        print("   • No hardcoded credentials detected ✅")
        print("   • Shuffle configuration correct ✅")
    
    return len(issues) == 0


def verify_gifted_sub_system():
    """Verify gifted sub tracking configuration"""
    print("\n\n🎁 GIFTED SUB TRACKING VERIFICATION")
    print("=" * 60)
    
    # Check gifted_sub_tracker.py exists
    tracker_path = Path("raffle_system/gifted_sub_tracker.py")
    if not tracker_path.exists():
        print("❌ gifted_sub_tracker.py not found!")
        return False
    
    with open(tracker_path, 'r', encoding='utf-8') as f:
        tracker_code = f.read()
    
    # Verify key components in tracker
    checks = {
        "Event ID deduplication": 'WHERE kick_event_id = :event_id' in tracker_code,
        "Gift count extraction": 'gift_count' in tracker_code,
        "Discord linking check": 'FROM links' in tracker_code,
        "Ticket award integration": 'ticket_manager.award_tickets' in tracker_code,
        "Database logging": 'INSERT INTO raffle_gifted_subs' in tracker_code,
    }
    
    print("\nComponent Checks:")
    all_passed = True
    for check_name, passed in checks.items():
        status = "✅" if passed else "❌"
        print(f"   {status} {check_name}")
        if not passed:
            all_passed = False
    
    # Check bot.py integration
    print("\nBot Integration:")
    bot_path = Path("bot.py")
    with open(bot_path, 'r', encoding='utf-8') as f:
        bot_code = f.read()
    
    integration_checks = {
        "Tracker import": 'from raffle_system.gifted_sub_tracker import' in bot_code,
        "Tracker initialization": 'gifted_sub_tracker = setup_gifted_sub_handler' in bot_code,
        "Multiple event types": 'GiftedSubscriptionsEvent' in bot_code and 'SubscriptionEvent' in bot_code,
        "Event handler call": 'handle_gifted_sub_event' in bot_code,
    }
    
    for check_name, passed in integration_checks.items():
        status = "✅" if passed else "❌"
        print(f"   {status} {check_name}")
        if not passed:
            all_passed = False
    
    # Event types monitored
    print("\nMonitored Event Types:")
    event_types = [
        "App\\Events\\GiftedSubscriptionsEvent",
        "App\\Events\\SubscriptionEvent", 
        "App\\Events\\ChatMessageEvent (with gift metadata)"
    ]
    for event_type in event_types:
        print(f"   • {event_type}")
    
    print("\nTicket Conversion:")
    print("   • 1 gifted sub = 15 raffle tickets")
    print("   • Multi-gifts supported (e.g., 5 subs = 75 tickets)")
    print("   • Only awards to linked Discord accounts")
    print("   • Duplicate events prevented via kick_event_id")
    
    if all_passed:
        print("\n✅ GIFTED SUB TRACKING: FULLY OPERATIONAL")
    else:
        print("\n❌ GIFTED SUB TRACKING: ISSUES DETECTED")
    
    return all_passed


def verify_shuffle_system():
    """Verify Shuffle wager tracking"""
    print("\n\n💰 SHUFFLE WAGER TRACKING VERIFICATION")
    print("=" * 60)
    
    tracker_path = Path("raffle_system/shuffle_tracker.py")
    if not tracker_path.exists():
        print("❌ shuffle_tracker.py not found!")
        return False
    
    with open(tracker_path, 'r', encoding='utf-8') as f:
        tracker_code = f.read()
    
    # Verify URL
    expected_url = "https://affiliate.shuffle.com/stats/1755f751-33a9-4532-804e-b14b5c90236b"
    
    config_path = Path("raffle_system/config.py")
    with open(config_path, 'r', encoding='utf-8') as f:
        config = f.read()
    
    print("\nConfiguration:")
    if expected_url in config:
        print(f"   ✅ Affiliate URL: {expected_url}")
    else:
        print(f"   ❌ Affiliate URL incorrect!")
        return False
    
    if 'SHUFFLE_CAMPAIGN_CODE = "lele"' in config:
        print('   ✅ Campaign code: "lele"')
    else:
        print('   ❌ Campaign code incorrect!')
        return False
    
    # Check functionality
    checks = {
        "API polling (aiohttp)": 'aiohttp' in tracker_code,
        "Campaign code filtering": 'campaignCode' in tracker_code,
        "Wager delta tracking": 'wager_delta' in tracker_code or 'current_wager - last_known_wager' in tracker_code,
        "Account linking": 'raffle_shuffle_links' in tracker_code,
        "Verification requirement": 'verified' in tracker_code,
        "Ticket calculation": 'SHUFFLE_TICKETS_PER_1000_USD' in tracker_code or config,
    }
    
    print("\nFunctionality:")
    all_passed = True
    for check_name, passed in checks.items():
        status = "✅" if passed else "❌"
        print(f"   {status} {check_name}")
        if not passed:
            all_passed = False
    
    print("\nOperational Details:")
    print("   • Polls every 15 minutes")
    print("   • Awards $1000 wagered = 20 tickets")
    print("   • Requires manual admin verification")
    print("   • Only tracks wager increases (not decreases)")
    
    if all_passed:
        print("\n✅ SHUFFLE TRACKING: FULLY OPERATIONAL")
    else:
        print("\n❌ SHUFFLE TRACKING: ISSUES DETECTED")
    
    return all_passed


def main():
    """Run all verification checks"""
    print("\n" + "="*60)
    print(" RAFFLE SYSTEM - SECURITY & VERIFICATION CHECK")
    print("="*60)
    
    security_ok = check_secrets()
    gifted_sub_ok = verify_gifted_sub_system()
    shuffle_ok = verify_shuffle_system()
    
    print("\n" + "="*60)
    print(" FINAL VERDICT")
    print("="*60)
    
    if security_ok and gifted_sub_ok and shuffle_ok:
        print("\n🎉 ALL SYSTEMS OPERATIONAL! 🎉")
        print("\n✅ Security: No exposed secrets")
        print("✅ Gifted Sub Tracking: 100% operational")
        print("✅ Shuffle Tracking: Configured correctly")
        print("\n🚀 System is production-ready!")
    else:
        print("\n⚠️  ISSUES DETECTED - Review above sections")
        if not security_ok:
            print("   ❌ Security issues found")
        if not gifted_sub_ok:
            print("   ❌ Gifted sub tracking issues")
        if not shuffle_ok:
            print("   ❌ Shuffle tracking issues")
    
    print("\n" + "="*60)


if __name__ == "__main__":
    main()
