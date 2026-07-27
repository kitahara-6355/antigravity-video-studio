import sys
import traceback

def main():
    sys.path.insert(0, r"c:\Users\PC_User\Desktop\script\video-automation")
    sys.path.insert(0, r"c:\Users\PC_User\Desktop\script\video-automation\backend")
    
    try:
        import tests.test_admin_analytics_router
        print("Import success!")
    except Exception as e:
        traceback.print_exc()

if __name__ == "__main__":
    main()
