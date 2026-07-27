# satisfies: REQ-WAVE-01
import warnings
import logging
from typing import List, Any, Union, Optional
from collections.abc import Iterable, Mapping

logger = logging.getLogger(__name__)

# Handle ExceptionGroup compatibility for Python < 3.11
try:
    ExceptionGroup = ExceptionGroup
except NameError:
    class ExceptionGroup(BaseException):  # type: ignore
        pass

class WaveScheduler:
    """Wave-based Scheduler for orchestrating parallel execution batches.
    
    Groups ready-to-run tasks into 'waves' to limit concurrent executions
    and balance the load.
    """
    def __init__(self, default_wave_size: Any = 30):
        self.default_wave_size = self._validate_wave_size(default_wave_size, 30)

    def _validate_wave_size(self, wave_size: Any, fallback: int) -> int:
        """Validates and coerces a wave size to a positive integer.
        
        Args:
            wave_size: The value to validate.
            fallback: The fallback value if validation fails.
            
        Returns:
            A positive integer.
        """
        # Ensure fallback itself is a valid positive integer, otherwise default to 30
        if not isinstance(fallback, int) or isinstance(fallback, bool) or fallback <= 0:
            fallback = 30

        # None is a valid input indicating that the fallback/default value should be used without warning.
        if wave_size is None:
            return fallback

        # Exclude booleans explicitly since isinstance(True, int) is True, but it is invalid for size.
        if isinstance(wave_size, bool):
            msg = f"wave_size cannot be boolean: {wave_size}. Falling back to {fallback}."
            logger.warning(msg)
            warnings.warn(msg, UserWarning, stacklevel=3)
            return fallback

        # If it is already a clean int
        if isinstance(wave_size, int):
            if wave_size <= 0:
                msg = f"wave_size must be a positive integer, got {wave_size}. Falling back to {fallback}."
                logger.warning(msg)
                warnings.warn(msg, UserWarning, stacklevel=3)
                return fallback
            return wave_size

        is_exact_float = False
        try:
            # Handle float types specifically to avoid warning when it's equivalent to an integer
            if isinstance(wave_size, float) and wave_size.is_integer():
                temp_size = int(wave_size)
                is_exact_float = True
            else:
                temp_size = int(wave_size)
        except (TypeError, ValueError, OverflowError) as e:
            msg = f"Invalid wave_size '{wave_size}' (coercion failed): {e}. Falling back to {fallback}."
            logger.warning(msg)
            warnings.warn(msg, UserWarning, stacklevel=3)
            return fallback
        except (AssertionError, MemoryError, SystemError, RecursionError):
            raise
        except Exception as e:
            if isinstance(e, ExceptionGroup) and hasattr(e, "subgroup") and e.subgroup((AssertionError, MemoryError, SystemError, RecursionError)) is not None:
                raise
            msg = f"Unexpected error during wave_size '{wave_size}' validation: {e}. Falling back to {fallback}."
            logger.error(msg, exc_info=True)
            warnings.warn(msg, UserWarning, stacklevel=3)
            return fallback

        if temp_size <= 0:
            msg = f"wave_size must be a positive integer, got {wave_size}. Falling back to {fallback}."
            logger.warning(msg)
            warnings.warn(msg, UserWarning, stacklevel=3)
            return fallback

        if not is_exact_float:
            msg = f"wave_size '{wave_size}' was converted to integer {temp_size}."
            logger.warning(msg)
            warnings.warn(msg, UserWarning, stacklevel=3)

        return temp_size

    def schedule_waves(self, executable_tasks: Optional[Iterable[Mapping[str, Any]]], wave_size: Optional[int] = None) -> List[List[Mapping[str, Any]]]:
        """Groups executable tasks into execution waves.
        
        Args:
            executable_tasks: Iterable of tasks that are ready to run (dependencies resolved).
            wave_size: Override for maximum concurrent tasks per wave.
            
        Returns:
            A list of task groups (waves) to be executed sequentially.
        """
        if executable_tasks is None:
            logger.warning("executable_tasks is None. Returning empty list.")
            return []
            
        # Ensure executable_tasks is iterable but not a string, dict/Mapping, or bytes.
        if not isinstance(executable_tasks, Iterable) or isinstance(executable_tasks, (str, Mapping, bytes)):
            logger.warning(f"executable_tasks must be an iterable of tasks, got {type(executable_tasks)}. Returning empty list.")
            return []

        # Validate task contents to ensure they are mappings (dict-like objects)
        validated_tasks = []
        try:
            for index, task in enumerate(executable_tasks):
                if not isinstance(task, Mapping):
                    logger.warning(f"Task at index {index} is not a mapping: {task}. Ignoring.")
                else:
                    validated_tasks.append(task)
        except (AssertionError, MemoryError, SystemError, RecursionError):
            raise
        except Exception as e:
            if isinstance(e, ExceptionGroup) and hasattr(e, "subgroup") and e.subgroup((AssertionError, MemoryError, SystemError, RecursionError)) is not None:
                raise
            msg = f"Exception raised during task iteration: {e}. Scheduled only {len(validated_tasks)} tasks."
            logger.error(msg, exc_info=True)
            warnings.warn(msg, RuntimeWarning, stacklevel=2)
            
        size = self.default_wave_size
        if wave_size is not None:
            size = self._validate_wave_size(wave_size, self.default_wave_size)
            
        # Hard guard against non-positive size to prevent ValueError in range() step argument
        if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
            msg = f"Execution wave size {size} is invalid (must be a positive integer > 0). Falling back to 30."
            logger.error(msg)
            warnings.warn(msg, UserWarning, stacklevel=2)
            size = 30

        waves = []
        # Chunk tasks into wave sizes
        for i in range(0, len(validated_tasks), size):
            waves.append(validated_tasks[i:i + size])
            
        return waves
